"""Lot buyer calculator. Mirrors apps/web/src/lib/lot.ts — keep the two in sync (tests cover both)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional

from .models import LotSettings, LotSummary

CONDITION_PRESETS = {"NM": 100.0, "LP": 85.0, "MP": 70.0, "HP": 50.0}
BORDERLINE_TOLERANCE = 1.15  # asking up to 15% above max offer = borderline
UNCONFIRMED_BELOW = 0.5  # unverified matches under this confidence stay out of the totals


@dataclass
class LotLine:
    unit_price_usd: Optional[float]
    quantity: int = 1
    lang: str = "en"
    confirmed: bool = True  # False → low-confidence guess: shown separately, not counted


def is_confirmed(needs_review: bool, confidence: float, user_verified: bool) -> bool:
    return user_verified or not needs_review or confidence >= UNCONFIRMED_BELOW


def summarize(lines: Iterable[LotLine], s: LotSettings) -> LotSummary:
    total = priced = unpriced = liquid_n = bulk_n = unconfirmed_n = 0
    retail = liquid = bulk = adj_liquid = adj_bulk = unconfirmed_v = 0.0
    cond = s.condition_pct / 100.0
    ne = 1.0 - s.non_english_discount_pct / 100.0
    for ln in lines:
        q = max(0, ln.quantity)
        if q == 0:
            continue
        total += q
        if not ln.confirmed:
            unconfirmed_n += q
            unconfirmed_v += (ln.unit_price_usd or 0.0) * q
            continue
        if ln.unit_price_usd is None:
            unpriced += q
            continue
        priced += q
        value = ln.unit_price_usd * q
        adj = value * cond * (ne if ln.lang != "en" else 1.0)
        retail += value
        if ln.unit_price_usd >= s.bulk_cutoff_usd:
            liquid_n += q
            liquid += value
            adj_liquid += adj
        else:
            bulk_n += q
            bulk += value
            adj_bulk += adj
    max_offer = adj_liquid * s.target_buy_rate_pct / 100.0
    asking_usd: Optional[float] = None
    if s.asking_price is not None and s.asking_price > 0:
        asking_usd = s.asking_price / s.fx_rate_mxn_per_usd if s.currency == "MXN" else s.asking_price
    adjusted_lot = adj_liquid + adj_bulk
    margin = margin_pct = None
    verdict = "n/a"
    if asking_usd is not None:
        margin = adjusted_lot - asking_usd
        margin_pct = margin / asking_usd * 100.0
        if asking_usd <= max_offer:
            verdict = "good"
        elif asking_usd <= max_offer * BORDERLINE_TOLERANCE:
            verdict = "borderline"
        else:
            verdict = "pass"
    r2 = lambda v: round(v, 2)  # noqa: E731
    return LotSummary(
        total_cards=total, priced_cards=priced, unpriced_cards=unpriced, liquid_cards=liquid_n, bulk_cards=bulk_n,
        retail_total_usd=r2(retail), liquid_total_usd=r2(liquid), bulk_total_usd=r2(bulk),
        adjusted_liquid_usd=r2(adj_liquid), adjusted_bulk_usd=r2(adj_bulk), adjusted_lot_value_usd=r2(adjusted_lot),
        suggested_max_offer_usd=r2(max_offer), asking_price_usd=None if asking_usd is None else r2(asking_usd),
        estimated_margin_usd=None if margin is None else r2(margin),
        estimated_margin_pct=None if margin_pct is None else round(margin_pct, 1), verdict=verdict,  # type: ignore[arg-type]
        unconfirmed_cards=unconfirmed_n, unconfirmed_value_usd=r2(unconfirmed_v),
    )
