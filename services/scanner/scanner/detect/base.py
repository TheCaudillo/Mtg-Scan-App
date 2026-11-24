"""Stage 1 interface: find card slots in a page photo and produce normalized crops.

Any detector (OpenCV heuristics today, a fine-tuned YOLO11 tomorrow) only has to return
quads in page-pixel coordinates; cropping/deskewing is shared in `crops.py`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


@dataclass(eq=False)
class DetectedCard:
    quad: np.ndarray  # (4,2) float32, tl,tr,br,bl in original page pixels
    score: float = 1.0
    row: int = 0
    col: int = 0
    slot: int = 0
    inferred: bool = False  # filled from grid lattice rather than seen directly
    maybe_inner: bool = False  # box may be the coloured frame inside the black border


@dataclass
class CardCrops:
    card: np.ndarray  # upright BGR, CARD_W x CARD_H
    art: np.ndarray
    strip: np.ndarray  # zoomed, glare-normalized bottom-left collector strip
    set_symbol: np.ndarray
    name_bar: np.ndarray
    alt: Optional["CardCrops"] = None  # crops from the box grown to the outer card edge


@dataclass
class DetectionResult:
    cards: list[DetectedCard]
    method: str
    content_box: tuple[int, int, int, int]  # x,y,w,h after chrome stripping
    chrome_cropped: bool = False
    debug: dict = field(default_factory=dict)


class CardDetector(ABC):
    name: str = "base"

    @abstractmethod
    def detect(self, image: np.ndarray, grid: Optional[dict] = None) -> DetectionResult:
        """image: BGR page photo. grid: optional manual {'corners': [[x,y]*4], 'rows': r, 'cols': c}."""


def get_detector(name: str = "opencv") -> CardDetector:
    if name in ("opencv", "", None):
        from .opencv_binder import OpenCVBinderDetector
        return OpenCVBinderDetector()
    if name == "yolo11":
        from .yolo11 import YOLO11CardDetector
        return YOLO11CardDetector()
    raise ValueError(f"unknown detector {name!r}")
