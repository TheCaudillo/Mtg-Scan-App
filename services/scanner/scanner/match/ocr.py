"""Free local reader: Tesseract OCR on the collector strip and the name bar.

Reads e.g. "010/277 C" + "MID • EN" → collector_number=10, rarity=C, set=MID, lang=en.
Only a hint — every value is validated against scryfall.db before use. OCR never asserts
non-foil (dots are unreliable at phone resolution); it only reports an unambiguous ★.
"""
from __future__ import annotations

import asyncio
import difflib
import logging
import os
import re
import shutil
import subprocess
import threading
from typing import Optional

import cv2
import numpy as np

from ..db import ScryfallDB, normalize_name
from ..detect.base import CardCrops
from ..models import VisionRead
from .base import FieldReader

log = logging.getLogger(__name__)
# Tesseract's OpenMP threading oversubscribes the CPU when many cards are read at once — one
# thread per process plus a bounded number of concurrent processes is far faster.
_TESS_ENV = {**os.environ, "OMP_THREAD_LIMIT": "1"}
_OCR_SLOTS = threading.BoundedSemaphore(max(2, os.cpu_count() or 2))

LANG_MAP = {"JP": "ja", "SP": "es", "CS": "zhs", "CT": "zht"}
LANG_ALT = "EN|ES|FR|DE|IT|PT|JA|JP|KO|RU|ZHS|ZHT|SP"

CN_TOTAL_RE = re.compile(r"\b0*(\d{1,4}[a-z]?)\s*/\s*\d{2,4}\s*([CURMSLPT])?\b")
CN_RARITY_RE = re.compile(r"\b0*(\d{1,4}[a-z]?)\s+([CURMSLPT])\b")
RARITY_CN_RE = re.compile(r"\b([CURMSLPT])\s?0*(\d{2,4})\b")
SET_LANG_RE = re.compile(rf"\b([A-Z0-9]{{3,5}})([^A-Z0-9\n]{{0,4}})({LANG_ALT})\b")


def tesseract_available() -> bool:
    return shutil.which("tesseract") is not None


def prep_for_ocr(raw: np.ndarray, scale: float = 4.0) -> np.ndarray:
    gray = cv2.cvtColor(raw, cv2.COLOR_BGR2GRAY) if raw.ndim == 3 else raw
    gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if gray.mean() < 110:  # light-on-dark strip on black frames
        gray = 255 - gray
    return gray


def _ocr(gray: np.ndarray, psm: int = 6) -> str:
    ok, buf = cv2.imencode(".png", gray)
    if not ok:
        return ""
    try:
        with _OCR_SLOTS:
            r = subprocess.run(["tesseract", "stdin", "stdout", "--psm", str(psm), "-l", "eng"],
                               input=buf.tobytes(), capture_output=True, timeout=20, env=_TESS_ENV)
        return r.stdout.decode("utf-8", "ignore")
    except (subprocess.SubprocessError, OSError) as e:
        log.warning("tesseract failed: %s", e)
        return ""


def parse_strip(text: str) -> VisionRead:
    read = VisionRead(source="ocr")
    flat = " ".join(text.split())
    m = CN_TOTAL_RE.search(flat)
    if m:
        read.collector_number = m.group(1)
        read.rarity_letter = m.group(2)
    else:
        m = CN_RARITY_RE.search(flat)
        if m:
            read.collector_number, read.rarity_letter = m.group(1), m.group(2)
        else:
            m = RARITY_CN_RE.search(flat)
            if m:
                read.rarity_letter, read.collector_number = m.group(1), m.group(2)
    for line in text.splitlines():
        m = SET_LANG_RE.search(line)
        if m and not m.group(1).isdigit():
            read.set_code = m.group(1).lower()
            if "★" in m.group(2) or "*" in m.group(2):
                read.foil_symbol = "star"
            lang = m.group(3)
            read.language = LANG_MAP.get(lang, lang.lower())
            break
    return read


_NAME_POOL: dict[int, tuple[list[str], dict[str, str]]] = {}


def _name_pool(db: ScryfallDB) -> tuple[list[str], dict[str, str]]:
    key = id(db)
    if key not in _NAME_POOL:
        rows = db.conn.execute("SELECT DISTINCT name_norm, name FROM cards WHERE lang='en'").fetchall()
        norm_to_name = {r[0]: r[1] for r in rows}
        for r in db.conn.execute("SELECT DISTINCT n.name_norm, c.name FROM card_names n JOIN cards c ON c.id = n.card_id"):
            norm_to_name.setdefault(r[0], r[1])  # face names, localized printed names
        _NAME_POOL[key] = (list(norm_to_name), norm_to_name)
    return _NAME_POOL[key]


def fuzzy_title(db: ScryfallDB, texts: list[str], min_score: float = 80.0) -> Optional[str]:
    """Best card name for noisy title reads ('Wier there PYyweresteds' → None, 'Hightand Berserker' → ok)."""
    from rapidfuzz import fuzz, process

    pool, to_name = _name_pool(db)
    best: tuple[str, float] | None = None
    for t in texts:
        t = normalize_name(t)
        if len(t) < 6:
            continue
        # plain whole-string similarity: lenient partial scorers match stray words ("there")
        hit = process.extractOne(t, pool, scorer=fuzz.ratio, score_cutoff=min_score)
        if hit and (best is None or hit[1] > best[1]):
            best = (hit[0], hit[1])
    return to_name.get(best[0]) if best else None


def resolve_name(db: ScryfallDB, text: str) -> Optional[str]:
    """Map a noisy OCR'd title ('[Llanowar Elves.', 'Discover the [Impossible — i.') to a real card name."""
    n = normalize_name(text)
    toks = n.split()
    if not toks:
        return None
    # exact on progressively trimmed token windows
    for i in range(0, min(2, len(toks))):
        for j in range(len(toks), i, -1):
            cand = " ".join(toks[i:j])
            # the match must explain most of what was read — never a stray word like "there"
            if len(cand) < 6 or len(cand) < 0.6 * len(n):
                break
            rows = db.by_name(cand, limit=1)
            if rows:
                return rows[0].printed_name if rows[0].lang != "en" and rows[0].printed_name else rows[0].name
    # fuzzy among names sharing the first word
    first = max(toks[:2], key=len)
    if len(first) < 3:
        return None
    pool = [r[0] for r in db.conn.execute(
        "SELECT DISTINCT name_norm FROM card_names WHERE name_norm LIKE ? LIMIT 3000", (f"%{first}%",))]
    best = difflib.get_close_matches(n, pool, n=1, cutoff=0.82)
    if best:
        rows = db.by_name(best[0], limit=1)
        return rows[0].name if rows else None
    return None


class TesseractStripReader(FieldReader):
    name = "ocr"

    def __init__(self, db: Optional[ScryfallDB] = None):
        self.db = db

    async def read(self, crops: CardCrops) -> Optional[VisionRead]:
        from ..detect.crops import _cut

        raw_strip = _cut(crops.card, (0.03, 0.912, 0.42, 0.978))
        text = await asyncio.to_thread(_ocr, prep_for_ocr(raw_strip, 2.5), 6)
        read = parse_strip(text)
        # the detected box may be the card edge or the coloured frame inside the black border,
        # so read the title from a couple of vertical offsets
        titles: list[str] = []
        for box in ((0.03, 0.0, 0.80, 0.085), (0.05, 0.03, 0.80, 0.105)):
            t = await asyncio.to_thread(_ocr, prep_for_ocr(_cut(crops.card, box), 1.8), 7)
            t = " ".join(t.split())
            if len(normalize_name(t)) >= 4:
                titles.append(t)
        read.title_texts = titles
        if self.db is not None and titles:
            for t in titles:
                read.name = await asyncio.to_thread(resolve_name, self.db, t)
                if read.name:
                    break
            if not read.name:
                read.name = await asyncio.to_thread(fuzzy_title, self.db, titles)
        if not any([read.collector_number, read.set_code, read.name, read.title_texts]):
            return None
        return read
