"""FastAPI app: batches, page uploads, scan jobs (SSE progress), card edits, exports, want list.

Run: uvicorn scanner.api.main:app --reload --port 8000   (from services/scanner)
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal, Optional

from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import get_settings
from ..db import ScryfallDB
from ..exporters import EXPORTERS
from ..lot import CONDITION_PRESETS, LotLine, is_confirmed, summarize
from ..match import HybridMatcher
from ..models import (BatchCreate, BatchRecord, BoxesSpec, CardPatch, CardRecord, GridSpec, LotSettings, LotSummary,
                      PageRecord, Printing, WantList)
from ..pipeline import ScanPipeline, load_image, normalize_upload
from ..radar import detect_foil, to_printing
from ..store import Store, parse_wantlist
from .events import EventBus

log = logging.getLogger("scanner.api")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ALLOWED_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}


class State:
    db: ScryfallDB
    store: Store
    matcher: HybridMatcher
    pipeline: ScanPipeline
    bus: EventBus
    jobs: dict[str, asyncio.Task]


S = State()


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    s.uploads_dir.mkdir(parents=True, exist_ok=True)
    S.db = ScryfallDB()
    S.store = Store()
    S.matcher = HybridMatcher.from_settings(S.db)
    S.pipeline = ScanPipeline(S.matcher)
    S.bus = EventBus()
    S.jobs = {}
    log.info("scryfall.db: %s printings | matcher: %s", f"{S.db.count():,}", S.matcher.describe())
    yield


app = FastAPI(title="BinderScan MTG", version="0.1.0", lifespan=lifespan)
_settings = get_settings()
app.add_middleware(CORSMiddleware, allow_origins=_settings.cors_origins,
                   allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?",
                   allow_methods=["*"], allow_headers=["*"])
_settings.uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/files", StaticFiles(directory=str(_settings.uploads_dir)), name="files")


def _batch_or_404(batch_id: str) -> BatchRecord:
    b = S.store.get_batch(batch_id)
    if b is None:
        raise HTTPException(404, "batch not found")
    return b


# ---- meta ---------------------------------------------------------------------------------------
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "printings": S.db.count(), "sync": S.db.meta(), "matcher": S.matcher.describe(),
            "condition_presets": CONDITION_PRESETS}


# ---- batches ------------------------------------------------------------------------------------
@app.post("/api/batches", response_model=BatchRecord)
def create_batch(body: BatchCreate = Body(default_factory=BatchCreate)) -> BatchRecord:
    bid = uuid.uuid4().hex[:10]
    from datetime import datetime
    name = body.name or f"Lot {datetime.now().strftime('%b %d %H:%M')}"
    return S.store.create_batch(BatchRecord(id=bid, name=name))


@app.get("/api/batches")
def list_batches() -> list[dict]:
    return S.store.list_batches()


@app.get("/api/batches/{batch_id}", response_model=BatchRecord)
def get_batch(batch_id: str) -> BatchRecord:
    return _batch_or_404(batch_id)


@app.delete("/api/batches/{batch_id}")
def delete_batch(batch_id: str) -> dict:
    _batch_or_404(batch_id)
    S.store.delete_batch(batch_id)
    shutil.rmtree(get_settings().uploads_dir / batch_id, ignore_errors=True)
    return {"deleted": batch_id}


# ---- pages --------------------------------------------------------------------------------------
@app.post("/api/batches/{batch_id}/pages", response_model=list[PageRecord])
async def upload_pages(batch_id: str, files: list[UploadFile] = File(...)) -> list[PageRecord]:
    _batch_or_404(batch_id)
    out: list[PageRecord] = []
    bdir = get_settings().uploads_dir / batch_id
    bdir.mkdir(parents=True, exist_ok=True)
    for f in files:
        ext = Path(f.filename or "x.jpg").suffix.lower()
        if ext not in ALLOWED_EXT:
            raise HTTPException(415, f"unsupported file type: {f.filename}")
        pid = uuid.uuid4().hex[:10]
        raw = bdir / f"{pid}_raw{ext}"
        with open(raw, "wb") as fh:
            while chunk := await f.read(1 << 20):
                fh.write(chunk)
        dst = bdir / f"{pid}.jpg"
        try:
            w, h = await asyncio.to_thread(normalize_upload, raw, dst)
        except Exception as e:  # noqa: BLE001
            raw.unlink(missing_ok=True)
            raise HTTPException(422, f"could not read image {f.filename}: {e}") from e
        raw.unlink(missing_ok=True)
        page = PageRecord(id=pid, batch_id=batch_id, index=S.store.next_page_index(batch_id),
                          filename=f.filename or dst.name, image_url=f"/files/{batch_id}/{pid}.jpg", width=w, height=h)
        S.store.save_page(page)
        out.append(page)
    return out


@app.delete("/api/batches/{batch_id}/pages/{page_id}")
def delete_page(batch_id: str, page_id: str) -> dict:
    S.store.delete_page(page_id)
    return {"deleted": page_id}


class DetectRequest(BaseModel):
    grid: Optional[GridSpec] = None


class DetectPreview(BaseModel):
    method: str
    chrome_cropped: bool
    content_box: list[int]
    quads: list[list[dict]]


@app.post("/api/batches/{batch_id}/pages/{page_id}/detect", response_model=DetectPreview)
async def detect_preview(batch_id: str, page_id: str, body: DetectRequest = Body(default_factory=DetectRequest)) -> DetectPreview:
    """Run detection only so the user can review/adjust boxes before matching."""
    page = S.store.get_page(page_id)
    if page is None or page.batch_id != batch_id:
        raise HTTPException(404, "page not found")
    img = await asyncio.to_thread(load_image, get_settings().uploads_dir / batch_id / f"{page_id}.jpg")
    grid = body.grid.model_dump() if body.grid else None
    det = await asyncio.to_thread(S.pipeline.detect, img, grid)
    return DetectPreview(method=det.method, chrome_cropped=det.chrome_cropped, content_box=list(det.content_box),
                         quads=[[{"x": float(x), "y": float(y)} for x, y in c.quad] for c in det.cards])


# ---- scanning -----------------------------------------------------------------------------------
class ScanRequest(BaseModel):
    page_ids: Optional[list[str]] = None  # default: all pages not yet scanned (or all if rescan)
    rescan: bool = False
    grids: dict[str, GridSpec] = Field(default_factory=dict)
    boxes: dict[str, BoxesSpec] = Field(default_factory=dict)


async def _scan_job(batch_id: str, pages: list[PageRecord], req: ScanRequest) -> None:
    S.store.set_batch_status(batch_id, "scanning")
    S.bus.publish(batch_id, "batch", {"id": batch_id, "status": "scanning"})
    try:
        for page in pages:
            page.status, page.progress, page.message = "detecting", 0.0, None
            S.store.save_page(page)
            S.bus.publish(batch_id, "page", page)
            out_dir = get_settings().uploads_dir / batch_id / page.id
            shutil.rmtree(out_dir, ignore_errors=True)
            grid = req.grids[page.id].model_dump() if page.id in req.grids else None
            quads = [[p.model_dump() for p in q] for q in req.boxes[page.id].quads] if page.id in req.boxes else None
            done = 0

            def on_detect(det, records: list[CardRecord], page=page) -> None:
                page.status, page.card_count = "matching", len(records)
                page.chrome_cropped, page.content_box = det.chrome_cropped, list(det.content_box)
                page.message = f"{len(records)} cards via {det.method}"
                page.manual_grid = req.grids.get(page.id)
                S.store.save_page(page)
                S.store.replace_page_cards(page.id, records)
                S.bus.publish(batch_id, "page", page)
                for r in records:
                    S.bus.publish(batch_id, "card", r)

            def on_card(rec: CardRecord, page=page) -> None:
                nonlocal done
                done += 1
                S.store.save_card(rec)
                page.progress = done / max(1, page.card_count)
                S.bus.publish(batch_id, "card", rec)
                S.bus.publish(batch_id, "page", page)

            try:
                await S.pipeline.scan_page(get_settings().uploads_dir / batch_id / f"{page.id}.jpg", batch_id, page.id,
                                           out_dir, f"/files/{batch_id}/{page.id}", grid=grid, quads=quads,
                                           on_detect=on_detect, on_card=on_card)
                page.status, page.progress = "done", 1.0
            except Exception as e:  # noqa: BLE001
                log.exception("page %s failed", page.id)
                page.status, page.message = "error", str(e)[:300]
            S.store.save_page(page)
            S.bus.publish(batch_id, "page", page)
        S.store.set_batch_status(batch_id, "done")
    except asyncio.CancelledError:
        S.store.set_batch_status(batch_id, "error")
        raise
    finally:
        S.bus.publish(batch_id, "done", {"id": batch_id})
        S.jobs.pop(batch_id, None)


@app.post("/api/batches/{batch_id}/scan", status_code=202)
async def scan(batch_id: str, req: ScanRequest = Body(default_factory=ScanRequest)) -> dict:
    b = _batch_or_404(batch_id)
    if batch_id in S.jobs and not S.jobs[batch_id].done():
        raise HTTPException(409, "scan already running for this batch")
    pages = b.pages
    if req.page_ids:
        pages = [p for p in pages if p.id in set(req.page_ids)]
    elif not req.rescan:
        pages = [p for p in pages if p.status in ("uploaded", "error")]
    if not pages:
        return {"queued": 0}
    S.jobs[batch_id] = asyncio.create_task(_scan_job(batch_id, pages, req))
    return {"queued": len(pages), "page_ids": [p.id for p in pages]}


@app.get("/api/batches/{batch_id}/events")
async def events(batch_id: str) -> StreamingResponse:
    _batch_or_404(batch_id)
    return StreamingResponse(S.bus.stream(batch_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---- cards --------------------------------------------------------------------------------------
@app.patch("/api/cards/{card_id}", response_model=CardRecord)
def patch_card(card_id: str, patch: CardPatch) -> CardRecord:
    c = S.store.get_card(card_id)
    if c is None:
        raise HTTPException(404, "card not found")
    if patch.quantity is not None:
        c.quantity = patch.quantity
    if patch.lang is not None:
        c.lang = patch.lang.lower()
    printing_id = patch.scryfall_id or (c.selected.scryfall_id if c.selected else None)
    if patch.scryfall_id:
        if S.db.by_id(patch.scryfall_id) is None:
            raise HTTPException(422, "unknown Scryfall printing id")  # never accept unvalidated printings
        c.user_verified = True
    if printing_id:
        row = S.db.by_id(printing_id)
        fin_list = row.finishes if row else []
        if patch.finish is not None:
            if fin_list and patch.finish not in fin_list:
                raise HTTPException(422, f"{patch.finish} does not exist for this printing ({', '.join(fin_list)})")
            c.finish = patch.finish
            c.foil_detection = patch.finish  # user-confirmed
            c.user_verified = True
        elif patch.scryfall_id:
            c.foil_detection = detect_foil(fin_list, c.observed)
            if c.finish not in fin_list and fin_list:
                c.finish = fin_list[0]  # type: ignore[assignment]
        selected, src, price = S.matcher.resolver.reprice(printing_id, c.lang, c.finish, c.foil_detection)
        c.selected, c.price_source, c.unit_price_usd = selected, src, price
        c.flags = [f for f in c.flags if f not in ("non_english", "foil_price_inversion")]
        if selected.price_inversion:
            c.flags.append("foil_price_inversion")
        if c.lang != "en":
            c.flags.append("non_english")
        if not any(p.scryfall_id == selected.scryfall_id for p in c.candidates):
            c.candidates = [selected] + c.candidates[:3]
    if patch.user_verified is not None:
        c.user_verified = patch.user_verified
    if c.user_verified and c.selected:
        c.status, c.needs_review = "identified", False
    S.store.save_card(c)
    S.bus.publish(c.batch_id, "card", c)
    return c


@app.get("/api/search", response_model=list[Printing])
def search(q: str = Query(..., min_length=2), limit: int = Query(20, le=60)) -> list[Printing]:
    return [to_printing(r) for r in S.db.search(q, limit)]


@app.get("/api/printings/{scryfall_id}/alternatives", response_model=list[Printing])
def alternatives(scryfall_id: str) -> list[Printing]:
    row = S.db.by_id(scryfall_id)
    if row is None or not row.oracle_id:
        raise HTTPException(404, "printing not found")
    return [to_printing(r) for r in S.db.by_oracle(row.oracle_id, "en")]


# ---- lot math & exports -------------------------------------------------------------------------
@app.post("/api/batches/{batch_id}/summary", response_model=LotSummary)
def lot_summary(batch_id: str, settings: LotSettings = Body(default_factory=LotSettings)) -> LotSummary:
    b = _batch_or_404(batch_id)
    return summarize([LotLine(c.unit_price_usd, c.quantity, c.lang, is_confirmed(c.needs_review, c.confidence, c.user_verified))
                      for c in b.cards if c.selected], settings)


@app.get("/api/batches/{batch_id}/export")
def export(batch_id: str, format: Literal["csv", "manabox", "moxfield", "markdown"] = "csv",
           condition: Literal["NM", "LP", "MP", "HP"] = "NM", non_english_discount_pct: float = 20.0,
           bulk_cutoff_usd: float = 2.0) -> Response:
    b = _batch_or_404(batch_id)
    s = LotSettings(condition_label=condition, condition_pct=CONDITION_PRESETS[condition],
                    non_english_discount_pct=non_english_discount_pct, bulk_cutoff_usd=bulk_cutoff_usd)
    fn, mime, ext = EXPORTERS[format]
    body = fn(b, s)
    safe = "".join(ch if ch.isalnum() else "_" for ch in b.name).strip("_") or b.id
    suffix = "" if format in ("csv", "markdown") else f"_{format}"
    return Response(body, media_type=f"{mime}; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{safe}{suffix}.{ext}"'})


# ---- want list ----------------------------------------------------------------------------------
class WantListText(BaseModel):
    text: str


@app.get("/api/wantlist", response_model=WantList)
def get_wantlist() -> WantList:
    return S.store.get_wantlist()


@app.put("/api/wantlist", response_model=WantList)
def put_wantlist(body: WantListText | WantList) -> WantList:
    wl = parse_wantlist(body.text) if isinstance(body, WantListText) else body
    S.store.set_wantlist(wl)
    return wl


@app.get("/", response_class=PlainTextResponse)
def root() -> str:
    return "BinderScan MTG scanner API — see /docs"
