"""CSV / ManaBox / Moxfield / Markdown exports of a scanned batch."""
from __future__ import annotations

import csv
import io
from typing import Iterable

from .lot import CONDITION_PRESETS
from .models import BatchRecord, CardRecord, LotSettings

LANG_NAMES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "it": "Italian", "pt": "Portuguese",
              "ja": "Japanese", "ko": "Korean", "ru": "Russian", "zhs": "Chinese Simplified", "zht": "Chinese Traditional"}
MANABOX_CONDITION = {"NM": "near_mint", "LP": "lightly_played", "MP": "moderately_played", "HP": "heavily_played"}
MOXFIELD_CONDITION = {"NM": "Near Mint", "LP": "Lightly Played", "MP": "Moderately Played", "HP": "Heavily Played"}


def _exportable(batch: BatchRecord) -> Iterable[tuple[int, CardRecord]]:
    page_no = {p.id: p.index + 1 for p in batch.pages}
    for c in batch.cards:
        if c.selected is not None and c.quantity > 0:
            yield page_no.get(c.page_id, 0), c


def adjusted_value(c: CardRecord, s: LotSettings) -> float | None:
    if c.unit_price_usd is None:
        return None
    v = c.unit_price_usd * c.quantity * s.condition_pct / 100
    if c.lang != "en":
        v *= 1 - s.non_english_discount_pct / 100
    return round(v, 2)


def _fmt(v: float | None) -> str:
    return "" if v is None else f"{v:.2f}"


def detailed_csv(batch: BatchRecord, s: LotSettings) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Page", "Slot", "English Name", "Printed Name", "Language", "Set Code", "Set Name", "Collector #",
                "Rarity", "Finish", "Treatment", "Quantity", "Scryfall USD", "Scryfall USD Foil", "Scryfall USD Etched",
                "Unit Price USD", "Price Source", "Adjusted Value", "Confidence", "Needs Review", "Review Reasons",
                "Scryfall URL"])
    for page, c in _exportable(batch):
        p = c.selected
        assert p is not None
        w.writerow([page, c.slot, p.name, p.printed_name or (c.observed.printed_name if c.observed else "") or p.name,
                    c.lang, p.set_code.upper(), p.set_name, p.collector_number, p.rarity, c.finish,
                    "; ".join(p.treatments), c.quantity, _fmt(p.usd), _fmt(p.usd_foil), _fmt(p.usd_etched),
                    _fmt(c.unit_price_usd), c.price_source or "N/A", _fmt(adjusted_value(c, s)),
                    f"{c.confidence:.2f}", "yes" if c.needs_review and not c.user_verified else "no",
                    "; ".join(c.review_reasons), p.scryfall_uri])
    return out.getvalue()


def manabox_csv(batch: BatchRecord, s: LotSettings) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Name", "Set code", "Set name", "Collector number", "Foil", "Rarity", "Quantity", "Scryfall ID",
                "Purchase price", "Misprint", "Altered", "Condition", "Language", "Purchase price currency"])
    cond = MANABOX_CONDITION.get(s.condition_label, "near_mint")
    for _, c in _exportable(batch):
        p = c.selected
        assert p is not None
        foil = {"nonfoil": "normal", "foil": "foil", "etched": "etched"}[c.finish]
        w.writerow([p.name, p.set_code.upper(), p.set_name, p.collector_number, foil, p.rarity, c.quantity,
                    p.scryfall_id, _fmt(c.unit_price_usd), "false", "false", cond, c.lang, "USD"])
    return out.getvalue()


def moxfield_csv(batch: BatchRecord, s: LotSettings) -> str:
    out = io.StringIO()
    w = csv.writer(out, quoting=csv.QUOTE_ALL)
    w.writerow(["Count", "Tradelist Count", "Name", "Edition", "Condition", "Language", "Foil", "Tags",
                "Last Modified", "Collector Number", "Alter", "Proxy", "Purchase Price"])
    cond = MOXFIELD_CONDITION.get(s.condition_label, "Near Mint")
    for _, c in _exportable(batch):
        p = c.selected
        assert p is not None
        foil = {"nonfoil": "", "foil": "foil", "etched": "etched"}[c.finish]
        w.writerow([c.quantity, 0, p.name, p.set_code.lower(), cond, LANG_NAMES.get(c.lang, c.lang), foil, "",
                    "", p.collector_number, "False", "False", _fmt(c.unit_price_usd)])
    return out.getvalue()


def markdown_summary(batch: BatchRecord, s: LotSettings) -> str:
    from .lot import LotLine, is_confirmed, summarize
    rows = list(_exportable(batch))
    summ = summarize([LotLine(c.unit_price_usd, c.quantity, c.lang, is_confirmed(c.needs_review, c.confidence, c.user_verified))
                      for _, c in rows], s)
    lines = [f"# {batch.name}", "",
             f"**{summ.total_cards} cards** · Retail ${summ.retail_total_usd:,.2f} · Liquid (≥${s.bulk_cutoff_usd:.2f}) "
             f"${summ.liquid_total_usd:,.2f} · Bulk ${summ.bulk_total_usd:,.2f} · Suggested max offer "
             f"**${summ.suggested_max_offer_usd:,.2f}**"
             + (f" · {summ.unconfirmed_cards} unconfirmed (${summ.unconfirmed_value_usd:,.2f}) not counted"
                if summ.unconfirmed_cards else ""), "",
             "| Pg | Slot | Card | Set | # | Finish | Lang | Price | Treatment |",
             "|---:|---:|---|---|---:|---|---|---:|---|"]
    for page, c in sorted(rows, key=lambda t: -(t[1].unit_price_usd or 0)):
        p = c.selected
        assert p is not None
        price = f"${c.unit_price_usd:.2f}" if c.unit_price_usd is not None else "N/A"
        flag = " ⚠️" if c.needs_review and not c.user_verified else ""
        lines.append(f"| {page} | {c.slot} | [{p.name}]({p.scryfall_uri}){flag} | {p.set_code.upper()} | "
                     f"{p.collector_number} | {c.finish} | {c.lang} | {price} | {', '.join(p.treatments)} |")
    return "\n".join(lines) + "\n"


EXPORTERS = {"csv": (detailed_csv, "text/csv", "csv"), "manabox": (manabox_csv, "text/csv", "csv"),
             "moxfield": (moxfield_csv, "text/csv", "csv"), "markdown": (markdown_summary, "text/markdown", "md")}
__all__ = ["EXPORTERS", "CONDITION_PRESETS", "adjusted_value"]
