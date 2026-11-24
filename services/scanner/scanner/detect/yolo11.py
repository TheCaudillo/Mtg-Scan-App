"""Placeholder for a fine-tuned YOLO11 (oriented-box) card detector.

Drop-in plan: `pip install ultralytics`, train an OBB model on labelled binder pages, set
DETECTOR=yolo11 and YOLO_WEIGHTS=path/to/best.pt. Only `detect()` needs implementing — crops,
matching and the API are detector-agnostic.
"""
from __future__ import annotations

import os
from typing import Optional

import numpy as np

from .base import CardDetector, DetectedCard, DetectionResult
from .grid import order_cards


class YOLO11CardDetector(CardDetector):
    name = "yolo11"

    def __init__(self) -> None:
        weights = os.getenv("YOLO_WEIGHTS")
        if not weights:
            raise RuntimeError("DETECTOR=yolo11 requires YOLO_WEIGHTS=<path to .pt>")
        from ultralytics import YOLO  # type: ignore[import-not-found]
        self.model = YOLO(weights)

    def detect(self, image: np.ndarray, grid: Optional[dict] = None) -> DetectionResult:
        res = self.model.predict(image, verbose=False)[0]
        cards: list[DetectedCard] = []
        if getattr(res, "obb", None) is not None:
            for pts, conf in zip(res.obb.xyxyxyxy.cpu().numpy(), res.obb.conf.cpu().numpy()):
                cards.append(DetectedCard(quad=np.asarray(pts, np.float32), score=float(conf)))
        h, w = image.shape[:2]
        return DetectionResult(cards=order_cards(cards), method="yolo11", content_box=(0, 0, w, h))
