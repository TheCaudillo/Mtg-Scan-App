"""Scryfall validation + disambiguation (mandatory for every matcher mode).

Inputs are *untrusted hints*: visual-index hits and field reads (OCR / vision LLM).
Output printings come exclusively from scryfall.db. When the evidence can't separate
printings (same-art reprints, unreadable collector number, finish hidden by glare) we
return 2–4 ranked candidates with needs_review + review reasons instead of guessing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..db import CardRow, ScryfallDB, normalize_cn, normalize_name
from ..models import Printing, VisionRead
from ..radar import default_finish, detect_foil, price_inversion, priced_printing, to_printing, unit_price
from .base import MatchResult, VisualHit

W_VISUAL = 1.0
W_NAME = 0.6
W_SET = 0.8
W_CN = 0.8
W_TITLE = 0.5            # noisy-title similarity bonus (rapidfuzz partial ratio above 0.5)
TIE_EPS = 0.04
MAX_CANDIDATES = 4
VISUAL_MIN = 0.55        # below this a visual hit alone is not trusted
VISUAL_STRONG = 0.80
VISUAL_SURE = 0.88       # this similarity alone is decisive
VISUAL_MARGIN = 0.035    # top-1 minus top-2 (different artwork) needed below VISUAL_SURE
GLARE_GAP_USD = 2.0       # finish price gap that warrants a human look when foil is uncertain

CUE_TREATMENT = {
    "extended_art": "Extended Art", "borderless": "Borderless", "showcase": "Showcase",
    "retro_frame": "Retro Frame", "full_art": "Full Art", "secret_lair": "Secret Lair",
    "serialized": "Serialized",
}


@dataclass
class _Cand:
    row: CardRow
    visual: float = 0.0
    name: bool = False
    set_ok: bool = False
    cn_ok: bool = False
    cue: float = 0.0
    title_sim: float = 0.0
    sources: set[str] = field(default_factory=set)

    @property
    def score(self) -> float:
        return (W_VISUAL * self.visual + W_NAME * self.name + W_SET * self.set_ok + W_CN * self.cn_ok + self.cue
                + W_TITLE * max(0.0, self.title_sim - 0.5))


def merge_reads(reads: list[Optional[VisionRead]]) -> Optional[VisionRead]:
    """Combine OCR + vision reads; earlier reads in the list win field conflicts."""
    reads = [r for r in reads if r is not None]
    if not reads:
        return None
    out = reads[0].model_copy(deep=True)
    for r in reads[1:]:
        for k, v in r.model_dump().items():
            if k in ("source", "frame_cues"):
                continue
            if getattr(out, k) in (None, "", "unclear") and v not in (None, "", "unclear"):
                setattr(out, k, v)
        out.frame_cues = sorted(set(out.frame_cues) | set(r.frame_cues))
    out.source = "+".join(r.source for r in reads)
    return out


def _names_match(row: CardRow, read: VisionRead) -> bool:
    targets = {normalize_name(read.name), normalize_name(read.printed_name)} - {""}
    if not targets:
        return False
    names = {normalize_name(row.name), normalize_name(row.printed_name)} | {normalize_name(x) for x in row.name.split(" // ")}
    return bool(targets & names)


def _title_similarity(row: CardRow, texts: list[str]) -> float:
    try:
        from rapidfuzz import fuzz
    except ImportError:  # pragma: no cover
        return 0.0
    names = {normalize_name(x) for x in row.name.split(" // ")} | {normalize_name(row.printed_name)}
    names.discard("")
    return max((fuzz.partial_ratio(n, normalize_name(t)) / 100 for n in names for t in texts if len(n) >= 3), default=0.0)


class Resolver:
    def __init__(self, db: ScryfallDB):
        self.db = db

    def _english(self, rows: list[CardRow]) -> list[CardRow]:
        out = []
        for r in rows:
            if r.lang == "en":
                out.append(r)
            else:
                en = self.db.english_equivalent(r)
                out.append(en or r)
        return out

    def gather(self, hits: list[VisualHit], read: Optional[VisionRead]) -> dict[str, _Cand]:
        cands: dict[str, _Cand] = {}

        def add(row: CardRow, src: str) -> _Cand:
            c = cands.get(row.id)
            if c is None:
                c = cands[row.id] = _Cand(row)
            c.sources.add(src)
            return c

        # 1. visual hits → every English printing sharing the illustration
        for h in hits:
            if h.score < VISUAL_MIN * 0.85:
                continue
            for row in self.db.by_illustration(h.illustration_id, "en") or self.db.by_ids([h.card_id]):
                c = add(row, "visual")
                c.visual = max(c.visual, h.score)

        if read is not None:
            # 2. exact set + collector number read
            if read.set_code and read.collector_number:
                for row in self._english(self.db.by_set_cn(read.set_code, read.collector_number)):
                    add(row, "set_cn")
            # 3. name (English or localized printed name) → all printings of that oracle card
            for nm in (read.name, read.printed_name):
                if not nm:
                    continue
                oracle_ids = {r.oracle_id for r in self.db.by_name(nm, limit=50) if r.oracle_id}
                for oid in list(oracle_ids)[:3]:
                    for row in self.db.by_oracle(oid, "en"):
                        add(row, "name")
            # score evidence from the read
            cue_t = {CUE_TREATMENT[c] for c in read.frame_cues if c in CUE_TREATMENT}
            for c in cands.values():
                r = c.row
                c.name = _names_match(r, read)
                if read.title_texts and not c.name:
                    c.title_sim = _title_similarity(r, read.title_texts)
                if read.set_code:
                    c.set_ok = r.set_code == read.set_code.lower()
                if read.collector_number:
                    c.cn_ok = normalize_cn(r.collector_number) == normalize_cn(read.collector_number)
                if read.border and read.border != "unclear":
                    c.cue += 0.12 if r.border_color == read.border else -0.12
                p_treat = set(to_printing(r).treatments)
                for t in ("Extended Art", "Borderless", "Showcase", "Retro Frame", "Full Art"):
                    if t in cue_t and t in p_treat:
                        c.cue += 0.12
                    elif t in cue_t and t not in p_treat:
                        c.cue -= 0.08
                    elif t in p_treat and cue_t and t not in cue_t:
                        c.cue -= 0.05
                fin = set(r.finishes)
                if read.foil_symbol == "star" and "foil" not in fin and "etched" not in fin:
                    c.cue -= 0.2
                if read.foil_symbol == "dot" and fin and "nonfoil" not in fin:
                    c.cue -= 0.2
        return cands

    def resolve(self, hits: list[VisualHit], read: Optional[VisionRead], method: str) -> MatchResult:
        if read is not None and read.is_card is False and not hits:
            return MatchResult(None, [], 0.0, True, ["no_match"], method, observed=read)
        cands = self.gather(hits, read)
        if read is not None and (read.name or read.printed_name) and any(c.name for c in cands.values()):
            # a text read prunes visually-similar-but-different cards — unless the visual index
            # strongly disagrees (then keep both and flag visual_text_conflict)
            named = {k: c for k, c in cands.items() if c.name or (c.set_ok and c.cn_ok)}
            strong_visual = max((c.visual for c in cands.values()), default=0.0)
            named_visual = max((c.visual for c in named.values()), default=0.0)
            if named and (not hits or named_visual >= VISUAL_MIN or strong_visual < VISUAL_STRONG):
                cands = named
        if not cands:
            return MatchResult(None, [], 0.0, True, ["no_match"], method, observed=read,
                               lang=(read.language if read and read.language else "en"))

        def tiebreak(c: _Cand) -> tuple:
            p = c.row
            # among indistinguishable printings prefer the plain main-set one, then the cheapest:
            # conservative for a buyer, and the review flag tells them to check.
            plain = not (p.promo or p.set_code == "sld" or p.set_type in ("promo", "memorabilia"))
            price = p.usd if p.usd is not None else (p.usd_foil if p.usd_foil is not None else 1e9)
            return (-round(c.score, 3), not plain, price, p.released_at or "")

        ranked = sorted(cands.values(), key=tiebreak)
        best = ranked[0]
        top_score = best.score
        ties = [c for c in ranked if top_score - c.score <= TIE_EPS]
        reasons: list[str] = []

        # ---- confidence -------------------------------------------------------------------------
        # wrong CLIP matches cluster tightly (top-1 ≈ top-2); right ones stand out
        visual_sure = False
        if hits and best.visual > 0 and best.row.illustration_id == hits[0].illustration_id:
            others = [h.score for h in hits[1:] if h.illustration_id != hits[0].illustration_id]
            margin = hits[0].score - (others[0] if others else 0.0)
            visual_sure = hits[0].score >= VISUAL_SURE or (hits[0].score >= VISUAL_STRONG * 0.97 and margin >= VISUAL_MARGIN)
        exact = best.set_ok and best.cn_ok
        if exact and (best.name or best.visual >= VISUAL_MIN):
            conf = 0.97
        elif exact:
            conf = 0.85
        elif visual_sure and (best.name or not (read and (read.name or read.printed_name))):
            conf = 0.92 if best.name else (0.9 if len(ties) == 1 else 0.75)
        elif best.name and best.visual >= VISUAL_MIN:
            conf = 0.85 if len(ties) == 1 else 0.7
        elif best.name:
            conf = 0.7 if len(ties) == 1 else 0.55
        else:
            conf = max(0.2, min(0.55, best.visual - 0.3))  # ambiguous artwork match

        # ---- review reasons ---------------------------------------------------------------------
        if len(ties) > 1:
            same_art = len({c.row.illustration_id for c in ties}) == 1
            reasons.append("same_art_reprint" if same_art else "low_confidence")
            if read is None or not read.collector_number:
                reasons.append("collector_number_unreadable")
        if read and (read.name or read.printed_name) and best.visual >= VISUAL_MIN and not best.name and not exact:
            reasons.append("visual_text_conflict")
        if conf < 0.6 and "low_confidence" not in reasons:
            reasons.append("low_confidence")

        # targeted choice may be applied by the caller; build result now
        physical_lang = (read.language if read and read.language else "en")
        sel_row = self._localized(best.row, physical_lang)
        selected, price_source = priced_printing(self.db, sel_row, physical_lang)
        selected.score = round(best.score, 4)
        detection = detect_foil(selected.finishes, read)
        finish = default_finish(detection, selected.finishes)
        flags: list[str] = []
        if price_inversion(selected):
            flags.append("foil_price_inversion")
        if detection == "uncertain" and len(set(selected.finishes) & {"nonfoil", "foil", "etched"}) > 1:
            prices = [v for v in (selected.usd, selected.usd_foil, selected.usd_etched) if v is not None]
            gap = (max(prices) - min(prices)) if len(prices) > 1 else 0.0
            if "foil_price_inversion" in flags:
                reasons.append("foil_price_inversion")
            elif gap >= GLARE_GAP_USD:
                reasons.append("glare_over_finish")
        if physical_lang != "en":
            flags.append("non_english")

        candidates = [to_printing(c.row, c.score) for c in ranked[:MAX_CANDIDATES]]
        if len(ties) > 1:  # make sure all tied printings are offered (up to the cap)
            seen = {p.scryfall_id for p in candidates}
            candidates += [to_printing(c.row, c.score) for c in ties if c.row.id not in seen]
            candidates = candidates[:MAX_CANDIDATES]
        return MatchResult(
            selected=selected, candidates=candidates, confidence=round(conf, 3),
            needs_review=bool(reasons), review_reasons=list(dict.fromkeys(reasons)), method=method,
            observed=read, lang=physical_lang, foil_detection=detection, finish=finish,
            unit_price_usd=unit_price(selected, finish, detection), price_source=price_source, flags=flags,
        )

    def _localized(self, en_row: CardRow, lang: str) -> CardRow:
        """If the physical card is e.g. Spanish and the DB has that printing (all_cards sync), use it."""
        if lang == "en":
            return en_row
        rows = self.db.by_set_cn(en_row.set_code, en_row.collector_number, lang=lang)
        return rows[0] if rows else en_row

    # ---- used by API patches ----------------------------------------------------------------
    def reprice(self, printing_id: str, lang: str, finish: str, detection: str) -> tuple[Printing, Optional[str], Optional[float]]:
        row = self.db.by_id(printing_id)
        if row is None:
            raise KeyError(printing_id)
        if row.lang != lang:
            row = self._localized(self.db.english_equivalent(row) or row, lang)
        p, src = priced_printing(self.db, row, lang)
        return p, src, unit_price(p, finish, detection)  # type: ignore[arg-type]
