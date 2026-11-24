"""Local SQLite mirror of Scryfall bulk data: schema, connection and lookup helpers.

Every identification the scanner returns must resolve to a row in this database —
set codes, collector numbers and prices are never produced from anywhere else.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id               TEXT PRIMARY KEY,
    oracle_id        TEXT,
    illustration_id  TEXT,
    name             TEXT NOT NULL,
    printed_name     TEXT,
    lang             TEXT NOT NULL,
    set_code         TEXT NOT NULL,
    set_name         TEXT,
    set_type         TEXT,
    collector_number TEXT NOT NULL,
    rarity           TEXT,
    released_at      TEXT,
    border_color     TEXT,
    frame            TEXT,
    frame_effects    TEXT,   -- JSON array
    promo_types      TEXT,   -- JSON array
    full_art         INTEGER,
    promo            INTEGER,
    finishes         TEXT,   -- JSON array
    type_line        TEXT,
    mana_cost        TEXT,
    oracle_text      TEXT,
    flavor_text      TEXT,
    artist           TEXT,
    usd              REAL,
    usd_foil         REAL,
    usd_etched       REAL,
    scryfall_uri     TEXT,
    image_normal     TEXT,
    image_small      TEXT,
    image_art_crop   TEXT,
    name_norm        TEXT,
    printed_name_norm TEXT,
    updated_at       TEXT
);
CREATE INDEX IF NOT EXISTS ix_cards_name ON cards(name);
CREATE INDEX IF NOT EXISTS ix_cards_name_norm ON cards(name_norm);
CREATE INDEX IF NOT EXISTS ix_cards_printed_name_norm ON cards(printed_name_norm);
CREATE INDEX IF NOT EXISTS ix_cards_set_cn ON cards(set_code, collector_number);
CREATE INDEX IF NOT EXISTS ix_cards_illustration ON cards(illustration_id);
CREATE INDEX IF NOT EXISTS ix_cards_oracle ON cards(oracle_id);
CREATE INDEX IF NOT EXISTS ix_cards_lang ON cards(lang);

-- every face name / printed name, normalised, for multi-face and localized lookups
CREATE TABLE IF NOT EXISTS card_names (
    card_id   TEXT NOT NULL,
    name_norm TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_card_names_norm ON card_names(name_norm);
CREATE INDEX IF NOT EXISTS ix_card_names_card ON card_names(card_id);

CREATE TABLE IF NOT EXISTS sync_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""

CARD_COLUMNS = [
    "id", "oracle_id", "illustration_id", "name", "printed_name", "lang", "set_code", "set_name",
    "set_type", "collector_number", "rarity", "released_at", "border_color", "frame", "frame_effects",
    "promo_types", "full_art", "promo", "finishes", "type_line", "mana_cost", "oracle_text",
    "flavor_text", "artist", "usd", "usd_foil", "usd_etched", "scryfall_uri", "image_normal",
    "image_small", "image_art_crop", "name_norm", "printed_name_norm", "updated_at",
]

_NON_ALNUM = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")


def normalize_name(s: str | None) -> str:
    """Lowercase, strip accents/punctuation: 'Comando cátaro' -> 'comando cataro'."""
    if not s:
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch)).lower()
    s = s.replace("’", "'").replace("'", "")
    s = _NON_ALNUM.sub(" ", s)
    return _WS.sub(" ", s).strip()


def normalize_cn(cn: str | None) -> str:
    """Collector numbers: strip leading zeros/whitespace, keep suffix letters/★ ('0123' -> '123')."""
    if not cn:
        return ""
    cn = str(cn).strip().lower().replace(" ", "")
    cn = cn.split("/")[0]  # '123/281' -> '123'
    m = re.match(r"^0*(\d+)(.*)$", cn)
    if m:
        return m.group(1) + m.group(2)
    return cn


@dataclass
class CardRow:
    """A validated Scryfall printing."""
    id: str
    oracle_id: str | None
    illustration_id: str | None
    name: str
    printed_name: str | None
    lang: str
    set_code: str
    set_name: str | None
    set_type: str | None
    collector_number: str
    rarity: str | None
    released_at: str | None
    border_color: str | None
    frame: str | None
    frame_effects: list[str]
    promo_types: list[str]
    full_art: bool
    promo: bool
    finishes: list[str]
    type_line: str | None
    mana_cost: str | None
    oracle_text: str | None
    flavor_text: str | None
    artist: str | None
    usd: float | None
    usd_foil: float | None
    usd_etched: float | None
    scryfall_uri: str | None
    image_normal: str | None
    image_small: str | None
    image_art_crop: str | None

    @classmethod
    def from_row(cls, r: sqlite3.Row) -> "CardRow":
        d = dict(r)
        return cls(
            id=d["id"], oracle_id=d["oracle_id"], illustration_id=d["illustration_id"], name=d["name"],
            printed_name=d["printed_name"], lang=d["lang"], set_code=d["set_code"], set_name=d["set_name"],
            set_type=d["set_type"], collector_number=d["collector_number"], rarity=d["rarity"],
            released_at=d["released_at"], border_color=d["border_color"], frame=d["frame"],
            frame_effects=json.loads(d["frame_effects"] or "[]"), promo_types=json.loads(d["promo_types"] or "[]"),
            full_art=bool(d["full_art"]), promo=bool(d["promo"]), finishes=json.loads(d["finishes"] or "[]"),
            type_line=d["type_line"], mana_cost=d["mana_cost"], oracle_text=d["oracle_text"],
            flavor_text=d["flavor_text"], artist=d["artist"], usd=d["usd"], usd_foil=d["usd_foil"],
            usd_etched=d["usd_etched"], scryfall_uri=d["scryfall_uri"], image_normal=d["image_normal"],
            image_small=d["image_small"], image_art_crop=d["image_art_crop"],
        )


def connect(path: Path | str | None = None, readonly: bool = False) -> sqlite3.Connection:
    path = Path(path) if path else get_settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    if readonly:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
    else:
        conn = sqlite3.connect(path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-65536")  # 64 MB
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


class ScryfallDB:
    """Thread-safe read helper over scryfall.db used by matchers and the API."""

    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else get_settings().db_path
        self._local = threading.local()

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = connect(self.path)
            init_schema(c)
            self._local.conn = c
        return c

    def _rows(self, sql: str, params: Iterable[Any] = ()) -> list[CardRow]:
        return [CardRow.from_row(r) for r in self.conn.execute(sql, tuple(params)).fetchall()]

    # ---- lookups ----------------------------------------------------------------------------
    def count(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]

    def by_id(self, card_id: str) -> CardRow | None:
        rows = self._rows("SELECT * FROM cards WHERE id = ?", (card_id,))
        return rows[0] if rows else None

    def by_ids(self, ids: list[str]) -> list[CardRow]:
        if not ids:
            return []
        q = ",".join("?" * len(ids))
        found = {c.id: c for c in self._rows(f"SELECT * FROM cards WHERE id IN ({q})", ids)}
        return [found[i] for i in ids if i in found]

    def by_set_cn(self, set_code: str, collector_number: str, lang: str | None = None) -> list[CardRow]:
        set_code = (set_code or "").strip().lower()
        cn = normalize_cn(collector_number)
        if not set_code or not cn:
            return []
        sql = "SELECT * FROM cards WHERE set_code = ? AND lower(collector_number) = ?"
        params: list[Any] = [set_code, cn]
        if lang:
            sql += " AND lang = ?"
            params.append(lang)
        rows = self._rows(sql, params)
        if not rows:
            # tolerate zero padding stored on Scryfall side ('001')
            rows = [r for r in self._rows("SELECT * FROM cards WHERE set_code = ?", [set_code])
                    if normalize_cn(r.collector_number) == cn and (not lang or r.lang == lang)]
        return rows

    def by_name(self, name: str, lang: str | None = None, limit: int = 300) -> list[CardRow]:
        """Exact (normalised) match on English name, any face name, or localized printed name."""
        n = normalize_name(name)
        if not n:
            return []
        sql = (
            "SELECT c.* FROM cards c WHERE c.id IN (SELECT card_id FROM card_names WHERE name_norm = ?)"
        )
        params: list[Any] = [n]
        if lang:
            sql += " AND c.lang = ?"
            params.append(lang)
        sql += " ORDER BY c.released_at DESC LIMIT ?"
        params.append(limit)
        return self._rows(sql, params)

    def by_illustration(self, illustration_id: str, lang: str | None = "en") -> list[CardRow]:
        sql = "SELECT * FROM cards WHERE illustration_id = ?"
        params: list[Any] = [illustration_id]
        if lang:
            sql += " AND lang = ?"
            params.append(lang)
        return self._rows(sql + " ORDER BY released_at DESC", params)

    def by_oracle(self, oracle_id: str, lang: str | None = "en") -> list[CardRow]:
        sql = "SELECT * FROM cards WHERE oracle_id = ?"
        params: list[Any] = [oracle_id]
        if lang:
            sql += " AND lang = ?"
            params.append(lang)
        return self._rows(sql + " ORDER BY released_at DESC", params)

    def search(self, q: str, limit: int = 20) -> list[CardRow]:
        """Prefix/substring search for the manual-search box in the review drawer."""
        n = normalize_name(q)
        if not n:
            return []
        rows = self._rows(
            "SELECT c.* FROM cards c JOIN (SELECT DISTINCT card_id FROM card_names WHERE name_norm LIKE ? LIMIT 400) m "
            "ON m.card_id = c.id WHERE c.lang = 'en' ORDER BY (c.name_norm = ?) DESC, c.released_at DESC LIMIT ?",
            (f"{n}%", n, limit),
        )
        if len(rows) < limit:
            seen = {r.id for r in rows}
            more = self._rows(
                "SELECT * FROM cards WHERE name_norm LIKE ? AND lang = 'en' ORDER BY released_at DESC LIMIT ?",
                (f"%{n}%", limit),
            )
            rows += [r for r in more if r.id not in seen][: limit - len(rows)]
        return rows

    def english_equivalent(self, card: CardRow) -> CardRow | None:
        """For a non-English printing, the English printing with the same set + collector number."""
        if card.lang == "en":
            return card
        rows = self.by_set_cn(card.set_code, card.collector_number, lang="en")
        if rows:
            return rows[0]
        # fall back to same illustration in English (e.g. language-exclusive promo numbering)
        if card.illustration_id:
            same = [r for r in self.by_illustration(card.illustration_id, "en") if r.set_code == card.set_code]
            if same:
                return same[0]
        return None

    def meta(self) -> dict[str, str]:
        return {r["key"]: r["value"] for r in self.conn.execute("SELECT key, value FROM sync_meta")}
