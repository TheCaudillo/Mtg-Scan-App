"""Lot buyer calculator math (mirrored by apps/web/src/lib/lot.ts)."""
import pytest

from scanner.lot import LotLine, summarize
from scanner.models import LotSettings

LINES = [
    LotLine(10.0, 1, "en"),   # liquid
    LotLine(5.0, 2, "es"),    # liquid, non-English
    LotLine(1.0, 3, "en"),    # bulk
    LotLine(0.25, 4, "es"),   # bulk, non-English
    LotLine(None, 1, "en"),   # unpriced
]


def test_totals_default_settings():
    s = summarize(LINES, LotSettings())
    assert s.total_cards == 11 and s.priced_cards == 10 and s.unpriced_cards == 1
    assert s.liquid_cards == 3 and s.bulk_cards == 7
    assert s.retail_total_usd == 24.0
    assert s.liquid_total_usd == 20.0
    assert s.bulk_total_usd == 4.0
    # adjusted: 10 + 10*0.8 = 18 liquid ; 3 + 1*0.8 = 3.8 bulk
    assert s.adjusted_liquid_usd == 18.0
    assert s.adjusted_bulk_usd == 3.8
    assert s.adjusted_lot_value_usd == 21.8
    assert s.suggested_max_offer_usd == pytest.approx(11.7)  # 65% of adjusted liquid
    assert s.verdict == "n/a"


def test_condition_and_discount():
    s = summarize(LINES, LotSettings(condition_pct=85, non_english_discount_pct=0))
    assert s.adjusted_liquid_usd == pytest.approx(20 * 0.85)


def test_bulk_cutoff_moves_cards():
    s = summarize(LINES, LotSettings(bulk_cutoff_usd=0.5))
    assert s.liquid_cards == 6 and s.bulk_cards == 4


def test_mxn_asking_price_and_verdicts():
    base = dict(currency="MXN", fx_rate_mxn_per_usd=20.0)
    good = summarize(LINES, LotSettings(asking_price=200, **base))  # $10 ≤ 11.70
    assert good.asking_price_usd == 10.0 and good.verdict == "good"
    assert good.estimated_margin_usd == pytest.approx(11.8)
    assert good.estimated_margin_pct == pytest.approx(118.0)
    border = summarize(LINES, LotSettings(asking_price=260, **base))  # $13 ≤ 11.70*1.15
    assert border.verdict == "borderline"
    bad = summarize(LINES, LotSettings(asking_price=500, **base))  # $25 > adjusted value $21.80
    assert bad.verdict == "pass" and bad.estimated_margin_usd < 0


def test_quantity_zero_ignored():
    s = summarize([LotLine(50.0, 0, "en")], LotSettings())
    assert s.total_cards == 0 and s.retail_total_usd == 0
