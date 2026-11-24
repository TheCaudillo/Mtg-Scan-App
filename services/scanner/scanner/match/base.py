"""Stage 2 interfaces.

* `VisualIndex`   — art embedding → top-K illustration_ids (OpenCLIP+FAISS today)
* `FieldReader`   — reads text fields off a card (local OCR, or a vision LLM)
* `CardMatcher`   — orchestrates both and returns Scryfall-validated results per card
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from ..detect.base import CardCrops
from ..models import Printing, VisionRead


@dataclass
class VisualHit:
    illustration_id: str
    card_id: str  # representative printing
    score: float  # cosine similarity


class VisualIndex(ABC):
    name = "visual"

    @abstractmethod
    def search(self, art_crops: list[np.ndarray], k: int = 8) -> list[list[VisualHit]]: ...

    @property
    @abstractmethod
    def size(self) -> int: ...


class FieldReader(ABC):
    name = "reader"

    @abstractmethod
    async def read(self, crops: CardCrops) -> Optional[VisionRead]: ...

    async def choose(self, crops: CardCrops, candidates: list[Printing]) -> Optional[int]:
        """Targeted disambiguation: return index into candidates, or None if unsure."""
        return None


@dataclass
class MatchResult:
    selected: Optional[Printing]
    candidates: list[Printing]
    confidence: float
    needs_review: bool
    review_reasons: list[str]
    method: str
    observed: Optional[VisionRead] = None
    lang: str = "en"
    foil_detection: str = "uncertain"
    finish: str = "nonfoil"
    unit_price_usd: Optional[float] = None
    price_source: Optional[str] = None
    flags: list[str] = field(default_factory=list)
    error: Optional[str] = None


class CardMatcher(ABC):
    @abstractmethod
    async def match_cards(self, crops: list[CardCrops], progress=None) -> list[MatchResult]:
        """Match all cards of a page. Must never raise for a single bad card."""
