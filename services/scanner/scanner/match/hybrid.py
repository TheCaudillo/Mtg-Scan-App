"""Default CardMatcher: local visual index + local OCR + optional vision LLM, always validated.

MATCHER_MODE:
  auto    visual index (if built) + OCR (if tesseract) + vision LLM only for unresolved cards (if key)
  clip    visual index + OCR only (fully offline)
  vision  vision LLM on every card (Day-1 mode, no index needed) + OCR
  ocr     OCR only (debug)
"""
from __future__ import annotations

import asyncio
import logging
from typing import Callable, Optional

import cv2

from ..config import get_settings
from ..db import ScryfallDB
from ..detect.base import CardCrops
from .base import CardMatcher, FieldReader, MatchResult, VisualHit, VisualIndex
from .resolver import VISUAL_MIN, Resolver, merge_reads

log = logging.getLogger(__name__)
Progress = Optional[Callable[[int, MatchResult], None]]


class HybridMatcher(CardMatcher):
    def __init__(self, db: ScryfallDB, visual: Optional[VisualIndex] = None, ocr: Optional[FieldReader] = None,
                 vision: Optional[FieldReader] = None, mode: str = "auto"):
        self.db = db
        self.resolver = Resolver(db)
        self.visual = visual
        self.ocr = ocr
        self.vision = vision
        self.mode = mode

    @classmethod
    def from_settings(cls, db: ScryfallDB | None = None) -> "HybridMatcher":
        s = get_settings()
        db = db or ScryfallDB()
        mode = s.matcher_mode
        visual = ocr = vision = None
        if mode in ("auto", "clip"):
            from .clip_faiss import ClipFaissIndex
            if ClipFaissIndex.available():
                try:
                    visual = ClipFaissIndex()
                except Exception as e:  # noqa: BLE001
                    log.warning("visual index unavailable: %s", e)
        from .ocr import TesseractStripReader, tesseract_available
        if tesseract_available() and mode != "none":
            ocr = TesseractStripReader(db)
        if mode in ("auto", "vision"):
            from .vision_llm import VisionLLMReader
            if VisionLLMReader.configured(s):
                vision = VisionLLMReader(s)
        return cls(db, visual, ocr, vision, mode)

    def describe(self) -> dict:
        return {
            "mode": self.mode,
            "visual_index": f"{self.visual.name} ({self.visual.size:,} artworks)" if self.visual else None,
            "ocr": self.ocr.name if self.ocr else None,
            "vision": self.vision.name if self.vision else None,
        }

    # ------------------------------------------------------------------------------------------
    def _visual_search(self, crops: list[CardCrops]) -> list[list[VisualHit]]:
        if not self.visual or not crops:
            return [[] for _ in crops]
        hits = self.visual.search([c.art for c in crops])
        # upside-down cards / pages: retry weak matches rotated 180°
        weak = [i for i, h in enumerate(hits) if not h or h[0].score < VISUAL_MIN]
        if weak:
            from ..detect.crops import crops_from_card
            flipped = [crops_from_card(cv2.rotate(crops[i].card, cv2.ROTATE_180)) for i in weak]
            rot_hits = self.visual.search([f.art for f in flipped])
            for i, f, rh in zip(weak, flipped, rot_hits):
                if rh and (not hits[i] or rh[0].score > hits[i][0].score + 0.05):
                    hits[i] = rh
                    crops[i] = f  # downstream OCR/vision should see the upright card
        return hits

    async def _match_one(self, crop: CardCrops, hits: list[VisualHit]) -> MatchResult:
        method_parts = []
        if hits:
            method_parts.append("clip")
        ocr_read = None
        if self.ocr:
            try:
                ocr_read = await self.ocr.read(crop)
                if ocr_read:
                    method_parts.append("ocr")
            except Exception as e:  # noqa: BLE001
                log.debug("ocr failed: %s", e)
        vision_read = None
        use_vision_now = self.vision is not None and (self.mode == "vision" or not hits)
        if use_vision_now:
            vision_read = await self.vision.read(crop)  # type: ignore[union-attr]
            method_parts.append(self.vision.name)  # type: ignore[union-attr]
        read = merge_reads([vision_read, ocr_read])
        result = self.resolver.resolve(hits, read, "+".join(method_parts) or "none")

        # escalate unresolved cards to the vision LLM (auto mode, index present)
        if self.vision and vision_read is None and (result.needs_review or result.selected is None):
            vision_read = await self.vision.read(crop)
            read = merge_reads([vision_read, ocr_read])
            method_parts.append(self.vision.name)
            result = self.resolver.resolve(hits, read, "+".join(method_parts))

        # targeted disambiguation among same-art reprints
        if self.vision and result.selected and "same_art_reprint" in result.review_reasons and len(result.candidates) > 1:
            idx = await self.vision.choose(crop, result.candidates)
            if idx is not None:
                chosen = result.candidates[idx]
                if read is None:
                    from ..models import VisionRead
                    read = VisionRead(source="choose")
                read = read.model_copy(update={"set_code": chosen.set_code, "collector_number": chosen.collector_number})
                result = self.resolver.resolve(hits, read, "+".join(method_parts + ["choose"]))
        return result

    async def match_cards(self, crops: list[CardCrops], progress: Progress = None) -> list[MatchResult]:
        try:
            hits_all = await asyncio.to_thread(self._visual_search, crops)
        except Exception as e:  # noqa: BLE001
            log.exception("visual search failed")
            hits_all = [[] for _ in crops]

        async def run(i: int) -> MatchResult:
            try:
                r = await self._match_one(crops[i], hits_all[i])
            except Exception as e:  # noqa: BLE001 — one bad card must never sink the page
                log.exception("card %d failed", i)
                r = MatchResult(None, [], 0.0, True, ["no_match"], "error", error=str(e)[:300])
            if progress:
                progress(i, r)
            return r

        return list(await asyncio.gather(*(run(i) for i in range(len(crops)))))
