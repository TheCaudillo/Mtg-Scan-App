"""Batch / page / card persistence (data/app.db, SQLite WAL, JSON documents)."""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from .config import get_settings
from .models import BatchRecord, CardRecord, PageRecord, WantList, utcnow

SCHEMA = """
CREATE TABLE IF NOT EXISTS batches (id TEXT PRIMARY KEY, name TEXT, created_at TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS pages (id TEXT PRIMARY KEY, batch_id TEXT, idx INTEGER, data TEXT);
CREATE INDEX IF NOT EXISTS ix_pages_batch ON pages(batch_id);
CREATE TABLE IF NOT EXISTS cards (id TEXT PRIMARY KEY, batch_id TEXT, page_id TEXT, slot INTEGER, data TEXT);
CREATE INDEX IF NOT EXISTS ix_cards_batch ON cards(batch_id);
CREATE INDEX IF NOT EXISTS ix_cards_page ON cards(page_id);
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or get_settings().app_db_path
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(SCHEMA)

    # ---- batches ----------------------------------------------------------------------------
    def create_batch(self, b: BatchRecord) -> BatchRecord:
        with self._lock:
            self.conn.execute("INSERT INTO batches VALUES (?,?,?,?)", (b.id, b.name, b.created_at, b.status))
            self.conn.commit()
        return b

    def list_batches(self) -> list[dict]:
        rows = self.conn.execute(
            "SELECT b.id, b.name, b.created_at, b.status, "
            "(SELECT COUNT(*) FROM pages p WHERE p.batch_id=b.id), (SELECT COUNT(*) FROM cards c WHERE c.batch_id=b.id) "
            "FROM batches b ORDER BY b.created_at DESC"
        ).fetchall()
        return [dict(id=r[0], name=r[1], created_at=r[2], status=r[3], pages=r[4], cards=r[5]) for r in rows]

    def set_batch_status(self, batch_id: str, status: str) -> None:
        with self._lock:
            self.conn.execute("UPDATE batches SET status=? WHERE id=?", (status, batch_id))
            self.conn.commit()

    def get_batch(self, batch_id: str) -> Optional[BatchRecord]:
        r = self.conn.execute("SELECT id, name, created_at, status FROM batches WHERE id=?", (batch_id,)).fetchone()
        if not r:
            return None
        pages = [PageRecord.model_validate_json(x[0]) for x in
                 self.conn.execute("SELECT data FROM pages WHERE batch_id=? ORDER BY idx", (batch_id,))]
        order = {p.id: p.index for p in pages}
        cards = [CardRecord.model_validate_json(x[0]) for x in
                 self.conn.execute("SELECT data FROM cards WHERE batch_id=?", (batch_id,))]
        cards.sort(key=lambda c: (order.get(c.page_id, 0), c.slot))
        return BatchRecord(id=r[0], name=r[1], created_at=r[2], status=r[3], pages=pages, cards=cards)

    def delete_batch(self, batch_id: str) -> None:
        with self._lock:
            for t in ("cards", "pages"):
                self.conn.execute(f"DELETE FROM {t} WHERE batch_id=?", (batch_id,))
            self.conn.execute("DELETE FROM batches WHERE id=?", (batch_id,))
            self.conn.commit()

    # ---- pages ------------------------------------------------------------------------------
    def save_page(self, p: PageRecord) -> None:
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO pages VALUES (?,?,?,?)", (p.id, p.batch_id, p.index, p.model_dump_json()))
            self.conn.commit()

    def get_page(self, page_id: str) -> Optional[PageRecord]:
        r = self.conn.execute("SELECT data FROM pages WHERE id=?", (page_id,)).fetchone()
        return PageRecord.model_validate_json(r[0]) if r else None

    def next_page_index(self, batch_id: str) -> int:
        r = self.conn.execute("SELECT COALESCE(MAX(idx), -1) FROM pages WHERE batch_id=?", (batch_id,)).fetchone()
        return int(r[0]) + 1

    def delete_page(self, page_id: str) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM cards WHERE page_id=?", (page_id,))
            self.conn.execute("DELETE FROM pages WHERE id=?", (page_id,))
            self.conn.commit()

    # ---- cards ------------------------------------------------------------------------------
    def replace_page_cards(self, page_id: str, cards: list[CardRecord]) -> None:
        with self._lock:
            self.conn.execute("DELETE FROM cards WHERE page_id=?", (page_id,))
            self.conn.executemany("INSERT INTO cards VALUES (?,?,?,?,?)",
                                  [(c.id, c.batch_id, c.page_id, c.slot, c.model_dump_json()) for c in cards])
            self.conn.commit()

    def save_card(self, c: CardRecord) -> None:
        c.updated_at = utcnow()
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO cards VALUES (?,?,?,?,?)",
                              (c.id, c.batch_id, c.page_id, c.slot, c.model_dump_json()))
            self.conn.commit()

    def get_card(self, card_id: str) -> Optional[CardRecord]:
        r = self.conn.execute("SELECT data FROM cards WHERE id=?", (card_id,)).fetchone()
        return CardRecord.model_validate_json(r[0]) if r else None

    # ---- want list --------------------------------------------------------------------------
    def get_wantlist(self) -> WantList:
        r = self.conn.execute("SELECT value FROM kv WHERE key='wantlist'").fetchone()
        return WantList.model_validate_json(r[0]) if r else WantList()

    def set_wantlist(self, wl: WantList) -> None:
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO kv VALUES ('wantlist', ?)", (wl.model_dump_json(),))
            self.conn.commit()


def parse_wantlist(text: str) -> WantList:
    """Accept plain names ('4 Lightning Bolt', 'Sol Ring (CMR)') or CSV with a Name/Card column."""
    import csv
    import io
    import re

    from .models import WantItem

    text = text.strip()
    items: list[WantItem] = []
    if not text:
        return WantList()
    first = text.splitlines()[0].lower()
    if "," in first and any(h in first for h in ("name", "card")):
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            low = {k.lower().strip(): (v or "").strip() for k, v in row.items() if k}
            name = low.get("name") or low.get("card") or low.get("card name")
            if not name:
                continue
            qty = low.get("quantity") or low.get("count") or low.get("qty") or "1"
            set_code = low.get("set") or low.get("set code") or low.get("edition") or None
            items.append(WantItem(name=name, set_code=(set_code or None) and set_code.lower(),
                                  quantity=int(qty) if qty.isdigit() else 1))
        return WantList(items=items)
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "//")):
            continue
        m = re.match(r"^(\d+)\s*x?\s+(.+)$", line)
        qty, name = (int(m.group(1)), m.group(2)) if m else (1, line)
        set_code = None
        sm = re.search(r"\(([A-Za-z0-9]{2,6})\)", name)
        if sm:
            set_code = sm.group(1).lower()
            name = name[: sm.start()].strip()
        name = re.sub(r"\s+\d+[a-z]?$", "", name).strip()  # trailing collector number
        items.append(WantItem(name=name, set_code=set_code, quantity=qty))
    return WantList(items=items)


def wantlist_names(wl: WantList) -> set[str]:
    from .db import normalize_name
    return {normalize_name(i.name) for i in wl.items}


__all__ = ["Store", "parse_wantlist", "wantlist_names", "json"]
