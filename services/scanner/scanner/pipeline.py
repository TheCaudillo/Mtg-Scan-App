"""Page scan pipeline: load → detect → crop → match → CardRecords (+ saved crop images)."""
from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np
from PIL import Image, ImageOps

from .detect import CardDetector, DetectedCard, DetectionResult, get_detector
from .detect.crops import make_crops
from .detect.grid import order_cards, order_quad
from .match.base import CardMatcher, MatchResult
from .models import CardRecord, Point

MAX_SIDE = 3200


def load_image(path: Path | str) -> np.ndarray:
    """EXIF-aware load (phone photos are often stored rotated), capped resolution, BGR."""
    im = Image.open(path)
    im = ImageOps.exif_transpose(im).convert("RGB")
    if max(im.size) > MAX_SIDE:
        s = MAX_SIDE / max(im.size)
        im = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
    return cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)


def normalize_upload(src: Path, dst: Path) -> tuple[int, int]:
    """Store an upright, size-capped JPEG so the browser overlay and the scanner share coordinates."""
    img = load_image(src)
    cv2.imwrite(str(dst), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
    return img.shape[1], img.shape[0]


def result_to_record(r: MatchResult, base: CardRecord) -> CardRecord:
    status = "unidentified" if r.selected is None else ("needs_review" if r.needs_review else "identified")
    if r.error and r.selected is None:
        status = "unidentified"
    return base.model_copy(update=dict(
        status=status, needs_review=r.needs_review or r.selected is None, review_reasons=r.review_reasons,
        confidence=r.confidence, match_method=r.method, observed=r.observed, selected=r.selected,
        candidates=r.candidates, lang=r.lang, foil_detection=r.foil_detection, finish=r.finish,
        unit_price_usd=r.unit_price_usd, price_source=r.price_source, flags=r.flags, error=r.error,
    ))


class ScanPipeline:
    def __init__(self, matcher: CardMatcher, detector: Optional[CardDetector] = None):
        self.detector = detector or get_detector("opencv")
        self.matcher = matcher

    def detect(self, image: np.ndarray, grid: Optional[dict] = None,
               quads: Optional[list[list[dict]]] = None) -> DetectionResult:
        if quads:
            cards = [DetectedCard(quad=order_quad(np.array([[p["x"], p["y"]] for p in q], np.float32))) for q in quads]
            h, w = image.shape[:2]
            return DetectionResult(order_cards(cards), "manual_boxes", (0, 0, w, h))
        return self.detector.detect(image, grid)

    async def scan_page(
        self, image_path: Path, batch_id: str, page_id: str, out_dir: Path, url_prefix: str,
        grid: Optional[dict] = None, quads: Optional[list[list[dict]]] = None,
        on_detect: Optional[Callable[[DetectionResult, list[CardRecord]], None]] = None,
        on_card: Optional[Callable[[CardRecord], None]] = None,
    ) -> tuple[DetectionResult, list[CardRecord]]:
        t0 = time.time()
        img = load_image(image_path)
        det = self.detect(img, grid, quads)
        out_dir.mkdir(parents=True, exist_ok=True)
        crops, records = [], []
        for c in det.cards:
            cid = uuid.uuid4().hex[:12]
            cr = make_crops(img, c.quad, c.maybe_inner)
            crops.append(cr)
            names = {}
            for kind, arr in (("card", cr.card), ("art", cr.art), ("strip", cr.strip)):
                fn = f"{cid}_{kind}.jpg"
                cv2.imwrite(str(out_dir / fn), arr, [cv2.IMWRITE_JPEG_QUALITY, 88])
                names[kind] = f"{url_prefix}/{fn}"
            records.append(CardRecord(
                id=cid, batch_id=batch_id, page_id=page_id, slot=c.slot, row=c.row, col=c.col,
                quad=[Point(x=float(x), y=float(y)) for x, y in c.quad],
                crop_url=names["card"], art_url=names["art"], strip_url=names["strip"], status="pending",
            ))
        if on_detect:
            on_detect(det, records)

        guessed = det.method == "uniform_grid"  # no card edges found: boxes are a blind guess

        def progress(i: int, r: MatchResult) -> None:
            if guessed and r.selected is not None and "low_confidence" not in r.review_reasons:
                r.review_reasons = ["low_confidence", *r.review_reasons]
                r.needs_review = True
                r.confidence = min(r.confidence, 0.3)
            records[i] = result_to_record(r, records[i])
            if on_card:
                on_card(records[i])

        await self.matcher.match_cards(crops, progress)
        det.debug["seconds"] = round(time.time() - t0, 2)
        return det, records
