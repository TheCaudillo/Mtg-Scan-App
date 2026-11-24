"""Pydantic v2 schemas shared by the pipeline, API and exporters."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Finish = Literal["nonfoil", "foil", "etched"]
FoilDetection = Literal["foil", "nonfoil", "etched", "uncertain"]
CardStatus = Literal["pending", "identified", "needs_review", "unidentified", "error"]
PriceSource = Literal["scryfall", "english_equivalent"]
ReviewReason = Literal[
    "same_art_reprint", "collector_number_unreadable", "glare_over_finish", "foil_price_inversion",
    "low_confidence", "visual_text_conflict", "language_uncertain", "no_match", "manual",
]


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Point(BaseModel):
    x: float
    y: float


class Printing(BaseModel):
    """A Scryfall printing that exists in the local DB (never synthesized)."""
    model_config = ConfigDict(from_attributes=True)

    scryfall_id: str
    oracle_id: Optional[str] = None
    illustration_id: Optional[str] = None
    name: str
    printed_name: Optional[str] = None
    lang: str = "en"
    set_code: str
    set_name: Optional[str] = None
    collector_number: str
    rarity: Optional[str] = None
    released_at: Optional[str] = None
    border_color: Optional[str] = None
    frame: Optional[str] = None
    frame_effects: list[str] = Field(default_factory=list)
    promo_types: list[str] = Field(default_factory=list)
    finishes: list[str] = Field(default_factory=list)
    treatments: list[str] = Field(default_factory=list)
    type_line: Optional[str] = None
    oracle_text: Optional[str] = None
    flavor_text: Optional[str] = None
    artist: Optional[str] = None
    usd: Optional[float] = None
    usd_foil: Optional[float] = None
    usd_etched: Optional[float] = None
    price_inversion: bool = False
    scryfall_uri: Optional[str] = None
    image_normal: Optional[str] = None
    image_small: Optional[str] = None
    image_art_crop: Optional[str] = None
    score: float = 0.0  # ranking score inside a candidate list


class VisionRead(BaseModel):
    """What a vision LLM / OCR read off the physical card. Untrusted until validated."""
    name: Optional[str] = None
    printed_name: Optional[str] = None
    language: Optional[str] = None  # ISO-ish code: en, es, ja ...
    set_code: Optional[str] = None
    collector_number: Optional[str] = None
    rarity_letter: Optional[str] = None  # C U R M S P L T
    foil_symbol: Optional[Literal["dot", "star", "none", "unclear"]] = None
    foil_sheen: Optional[Literal["clear", "none", "unclear"]] = None
    border: Optional[Literal["black", "white", "borderless", "silver", "gold", "unclear"]] = None
    frame_cues: list[str] = Field(default_factory=list)  # extended_art, showcase, retro, full_art ...
    text_snippet: Optional[str] = None
    is_card: bool = True
    confidence: Optional[float] = None
    source: str = "vision"


class CardRecord(BaseModel):
    id: str
    batch_id: str
    page_id: str
    slot: int
    row: int
    col: int
    quad: list[Point] = Field(default_factory=list)  # corners in page-image pixel coords (tl,tr,br,bl)
    crop_url: Optional[str] = None
    art_url: Optional[str] = None
    strip_url: Optional[str] = None
    status: CardStatus = "pending"
    needs_review: bool = False
    review_reasons: list[ReviewReason] = Field(default_factory=list)
    confidence: float = 0.0
    match_method: Optional[str] = None
    observed: Optional[VisionRead] = None
    selected: Optional[Printing] = None
    candidates: list[Printing] = Field(default_factory=list)
    lang: str = "en"
    foil_detection: FoilDetection = "uncertain"
    finish: Finish = "nonfoil"
    quantity: int = 1
    unit_price_usd: Optional[float] = None
    price_source: Optional[PriceSource] = None
    flags: list[str] = Field(default_factory=list)
    user_verified: bool = False
    error: Optional[str] = None
    updated_at: str = Field(default_factory=utcnow)


class PageRecord(BaseModel):
    id: str
    batch_id: str
    index: int
    filename: str
    image_url: str
    width: int = 0
    height: int = 0
    status: Literal["uploaded", "detecting", "matching", "done", "error"] = "uploaded"
    progress: float = 0.0
    message: Optional[str] = None
    chrome_cropped: bool = False
    content_box: Optional[list[int]] = None  # x,y,w,h after UI-chrome stripping
    card_count: int = 0
    manual_grid: Optional["GridSpec"] = None


class BatchRecord(BaseModel):
    id: str
    name: str
    created_at: str = Field(default_factory=utcnow)
    status: Literal["new", "scanning", "done", "error"] = "new"
    pages: list[PageRecord] = Field(default_factory=list)
    cards: list[CardRecord] = Field(default_factory=list)


class GridSpec(BaseModel):
    """Manual grid overlay chosen in the UI for heavily angled photos."""
    corners: list[Point] = Field(..., min_length=4, max_length=4)  # tl,tr,br,bl of the card area
    rows: int = Field(3, ge=1, le=6)
    cols: int = Field(3, ge=1, le=6)


class BoxesSpec(BaseModel):
    """User-adjusted card quads (overrides the detector)."""
    quads: list[list[Point]]


PageRecord.model_rebuild()


# ----- API payloads -----------------------------------------------------------------------------
class BatchCreate(BaseModel):
    name: Optional[str] = None


class CardPatch(BaseModel):
    scryfall_id: Optional[str] = None
    finish: Optional[Finish] = None
    lang: Optional[str] = None
    quantity: Optional[int] = Field(None, ge=0, le=999)
    user_verified: Optional[bool] = None


class LotSettings(BaseModel):
    asking_price: Optional[float] = None
    currency: Literal["USD", "MXN"] = "USD"
    fx_rate_mxn_per_usd: float = 18.0
    bulk_cutoff_usd: float = 2.0
    condition_pct: float = 100.0
    non_english_discount_pct: float = 20.0
    target_buy_rate_pct: float = 65.0
    condition_label: Literal["NM", "LP", "MP", "HP"] = "NM"


class LotSummary(BaseModel):
    total_cards: int
    priced_cards: int
    unpriced_cards: int
    liquid_cards: int
    bulk_cards: int
    retail_total_usd: float
    liquid_total_usd: float
    bulk_total_usd: float
    adjusted_liquid_usd: float
    adjusted_bulk_usd: float
    adjusted_lot_value_usd: float
    suggested_max_offer_usd: float
    asking_price_usd: Optional[float]
    estimated_margin_usd: Optional[float]
    estimated_margin_pct: Optional[float]
    verdict: Literal["good", "borderline", "pass", "n/a"]


class WantItem(BaseModel):
    name: str
    set_code: Optional[str] = None
    quantity: int = 1


class WantList(BaseModel):
    items: list[WantItem] = Field(default_factory=list)
