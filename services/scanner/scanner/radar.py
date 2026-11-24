"""Variant, finish and anomaly radar — everything here derives from Scryfall metadata
(plus, for foil detection, what was observed on the physical card)."""
from __future__ import annotations

from typing import Optional

from .db import CardRow, ScryfallDB
from .models import Finish, FoilDetection, Printing, VisionRead

RETRO_FRAMES = {"1993", "1997"}


def treatments(card: CardRow) -> list[str]:
    fx = set(card.frame_effects)
    promos = set(card.promo_types)
    out: list[str] = []
    if "extendedart" in fx:
        out.append("Extended Art")
    if card.border_color == "borderless":
        out.append("Borderless")
    if "showcase" in fx:
        out.append("Showcase")
    if card.frame in RETRO_FRAMES and (card.released_at or "") >= "2018-01-01":
        out.append("Retro Frame")
    if card.border_color == "white":
        out.append("White Border")
    if card.full_art:
        out.append("Full Art")
    if "surgefoil" in promos:
        out.append("Surge Foil")
    if "galaxyfoil" in promos:
        out.append("Galaxy Foil")
    if "textured" in promos:
        out.append("Textured Foil")
    if "serialized" in promos:
        out.append("Serialized")
    if card.set_code == "sld" or "secret lair" in (card.set_name or "").lower():
        out.append("Secret Lair")
    if card.promo and "Secret Lair" not in out:
        out.append("Promo")
    if card.rarity == "mythic":
        out.append("Mythic")
    return out


def price_inversion(card: CardRow | Printing) -> bool:
    """Non-foil priced above foil — buyer should double-check finish in person."""
    return card.usd is not None and card.usd_foil is not None and card.usd > card.usd_foil


def to_printing(card: CardRow, score: float = 0.0) -> Printing:
    return Printing(
        scryfall_id=card.id, oracle_id=card.oracle_id, illustration_id=card.illustration_id, name=card.name,
        printed_name=card.printed_name, lang=card.lang, set_code=card.set_code, set_name=card.set_name,
        collector_number=card.collector_number, rarity=card.rarity, released_at=card.released_at,
        border_color=card.border_color, frame=card.frame, frame_effects=card.frame_effects,
        promo_types=card.promo_types, finishes=card.finishes, treatments=treatments(card),
        type_line=card.type_line, oracle_text=card.oracle_text, flavor_text=card.flavor_text,
        artist=card.artist, usd=card.usd, usd_foil=card.usd_foil, usd_etched=card.usd_etched,
        price_inversion=price_inversion(card), scryfall_uri=card.scryfall_uri, image_normal=card.image_normal,
        image_small=card.image_small, image_art_crop=card.image_art_crop, score=round(score, 4),
    )


def detect_foil(finishes: list[str], read: Optional[VisionRead]) -> FoilDetection:
    """Conservative: only say foil/nonfoil when Scryfall or a clear physical marker proves it."""
    fin = set(finishes)
    if fin == {"foil"}:
        return "foil"
    if fin == {"nonfoil"}:
        return "nonfoil"
    if fin == {"etched"}:
        return "etched"
    if read is None:
        return "uncertain"
    if read.foil_symbol == "star" or read.foil_sheen == "clear":
        return "etched" if fin == {"etched", "foil"} and read.foil_sheen != "clear" else "foil"
    if read.foil_symbol == "dot" and read.foil_sheen in ("none", None):
        return "nonfoil"
    return "uncertain"


def default_finish(detection: FoilDetection, finishes: list[str]) -> Finish:
    if detection in ("foil", "nonfoil", "etched") and (not finishes or detection in finishes):
        return detection  # type: ignore[return-value]
    if "nonfoil" in finishes:
        return "nonfoil"
    if finishes:
        return finishes[0]  # type: ignore[return-value]
    return "nonfoil"


def unit_price(p: Printing, finish: Finish, detection: FoilDetection = "nonfoil") -> Optional[float]:
    """USD price for the chosen finish. Never fabricated: None when Scryfall has none.
    When foil status is uncertain we use the *lower* of the available finish prices."""
    by_finish = {"nonfoil": p.usd, "foil": p.usd_foil, "etched": p.usd_etched}
    if detection == "uncertain":
        allowed = set(p.finishes) or set(by_finish)
        avail = [v for k, v in by_finish.items() if v is not None and k in allowed]
        return min(avail) if avail else None
    return by_finish.get(finish)


def priced_printing(db: ScryfallDB, card: CardRow, physical_lang: str) -> tuple[Printing, Optional[str]]:
    """Return a Printing whose prices are valid for pricing, plus price_source.

    * English printing, English card               -> own prices, 'scryfall'
    * Non-English DB row (e.g. Spanish printing)    -> prices of the EN printing with same set+cn
    * English DB row but physical card is Spanish   -> EN prices, 'english_equivalent'
    """
    p = to_printing(card)
    if card.lang != "en":
        en = db.english_equivalent(card)
        if en is not None:
            p.usd, p.usd_foil, p.usd_etched = en.usd, en.usd_foil, en.usd_etched
            p.price_inversion = price_inversion(p)
            return p, "english_equivalent"
        has_any = any(v is not None for v in (card.usd, card.usd_foil, card.usd_etched))
        return p, ("scryfall" if has_any else None)
    has_any = any(v is not None for v in (p.usd, p.usd_foil, p.usd_etched))
    if not has_any:
        return p, None
    return p, ("english_equivalent" if physical_lang != "en" else "scryfall")
