"""Scryfall bulk-data mirror.

Usage (via scripts/sync_scryfall.py or `python -m scanner.scryfall_sync`):
    sync                       full default_cards sync (EN + cards with no EN printing)
    sync --source all_cards --langs en,es   also ingest Spanish printings (printed names!)
    sync --since 2023-01-01    only keep printings released on/after a date (fast test DB)
    sync --sets mid,inr,fdn    only keep given sets
    prices                     fast daily price refresh (updates price columns only)
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import httpx

from .config import get_settings
from .db import CARD_COLUMNS, connect, init_schema, normalize_name

BULK_INDEX_URL = "https://api.scryfall.com/bulk-data"


def _client() -> httpx.Client:
    s = get_settings()
    return httpx.Client(
        headers={"User-Agent": s.user_agent, "Accept": "application/json;q=0.9,*/*;q=0.8"},
        timeout=httpx.Timeout(60.0, read=300.0),
        follow_redirects=True,
    )


def bulk_entry(bulk_type: str) -> dict[str, Any]:
    with _client() as c:
        r = c.get(BULK_INDEX_URL)
        r.raise_for_status()
        for entry in r.json()["data"]:
            if entry["type"] == bulk_type:
                return entry
    raise RuntimeError(f"bulk type {bulk_type!r} not found at {BULK_INDEX_URL}")


def download_bulk(bulk_type: str, force: bool = False) -> Path:
    """Download (and cache by updated_at) a bulk file. Supports both the current gzipped
    JSONL (`jsonl_download_uri`) and the legacy JSON array (`download_uri`)."""
    entry = bulk_entry(bulk_type)
    url = entry.get("jsonl_download_uri") or entry.get("download_uri")
    if not url:
        raise RuntimeError(f"no download URI in bulk entry: {entry}")
    out_dir = get_settings().bulk_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / Path(url).name
    if dest.exists() and not force:
        print(f"[sync] using cached {dest.name}")
        return dest
    for old in out_dir.glob(f"{bulk_type.replace('_', '-')}-*"):
        old.unlink(missing_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    t0 = time.time()
    with _client() as c, c.stream("GET", url) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or entry.get("compressed_size") or entry.get("size") or 0)
        done = 0
        last = 0.0
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if time.time() - last > 2:
                    pct = f"{100 * done / total:5.1f}%" if total else ""
                    print(f"[sync] downloading {dest.name}: {done / 1e6:7.1f} MB {pct}", flush=True)
                    last = time.time()
    tmp.rename(dest)
    print(f"[sync] downloaded {done / 1e6:.1f} MB in {time.time() - t0:.1f}s")
    return dest


def iter_cards(path: Path) -> Iterator[dict[str, Any]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        first = f.read(1)
        while first and first.isspace():
            first = f.read(1)
        if first == "[":  # legacy JSON array
            data = json.loads(first + f.read())
            yield from data
            return
        line0 = first + f.readline()
        if line0.strip():
            yield json.loads(line0)
        for line in f:
            line = line.strip().rstrip(",")
            if line and line not in ("[", "]"):
                yield json.loads(line)


def _price(v: Any) -> float | None:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _images(card: dict[str, Any]) -> dict[str, str | None]:
    uris = card.get("image_uris")
    if not uris and card.get("card_faces"):
        uris = card["card_faces"][0].get("image_uris")
    uris = uris or {}
    return {"normal": uris.get("normal"), "small": uris.get("small"), "art_crop": uris.get("art_crop")}


def card_to_row(card: dict[str, Any], now: str) -> tuple[tuple[Any, ...], list[str]]:
    faces = card.get("card_faces") or []
    face0 = faces[0] if faces else {}
    imgs = _images(card)
    prices = card.get("prices") or {}
    illustration_id = card.get("illustration_id") or face0.get("illustration_id")
    printed_name = card.get("printed_name") or face0.get("printed_name")
    oracle_text = card.get("oracle_text")
    if oracle_text is None and faces:
        oracle_text = "\n//\n".join(f.get("oracle_text", "") for f in faces)
    flavor = card.get("flavor_text") or face0.get("flavor_text")
    row = {
        "id": card["id"],
        "oracle_id": card.get("oracle_id") or face0.get("oracle_id"),
        "illustration_id": illustration_id,
        "name": card["name"],
        "printed_name": printed_name,
        "lang": card.get("lang", "en"),
        "set_code": card["set"].lower(),
        "set_name": card.get("set_name"),
        "set_type": card.get("set_type"),
        "collector_number": card["collector_number"],
        "rarity": card.get("rarity"),
        "released_at": card.get("released_at"),
        "border_color": card.get("border_color"),
        "frame": card.get("frame"),
        "frame_effects": json.dumps(card.get("frame_effects") or []),
        "promo_types": json.dumps(card.get("promo_types") or []),
        "full_art": int(bool(card.get("full_art"))),
        "promo": int(bool(card.get("promo"))),
        "finishes": json.dumps(card.get("finishes") or []),
        "type_line": card.get("type_line") or face0.get("type_line"),
        "mana_cost": card.get("mana_cost") or face0.get("mana_cost"),
        "oracle_text": oracle_text,
        "flavor_text": flavor,
        "artist": card.get("artist") or face0.get("artist"),
        "usd": _price(prices.get("usd")),
        "usd_foil": _price(prices.get("usd_foil")),
        "usd_etched": _price(prices.get("usd_etched")),
        "scryfall_uri": card.get("scryfall_uri"),
        "image_normal": imgs["normal"],
        "image_small": imgs["small"],
        "image_art_crop": imgs["art_crop"],
        "name_norm": normalize_name(card["name"]),
        "printed_name_norm": normalize_name(printed_name),
        "updated_at": now,
    }
    names = {normalize_name(card["name"])}
    for f in faces:
        names.add(normalize_name(f.get("name")))
        names.add(normalize_name(f.get("printed_name")))
    names.add(normalize_name(printed_name))
    names.discard("")
    return tuple(row[c] for c in CARD_COLUMNS), sorted(names)


def _keep(card: dict[str, Any], langs: set[str] | None, sets: set[str] | None, since: str | None) -> bool:
    if card.get("object") != "card" or card.get("digital"):
        return False
    if "paper" not in (card.get("games") or ["paper"]):
        return False
    if card.get("layout") in {"art_series", "token", "double_faced_token", "emblem"} and card.get("set_type") != "memorabilia":
        # tokens/art cards rarely matter for lot value; skip to keep the DB lean
        return False
    if langs and card.get("lang", "en") not in langs:
        return False
    if sets and card.get("set", "").lower() not in sets:
        return False
    if since and (card.get("released_at") or "") < since:
        return False
    return True


def sync(source: str = "default_cards", langs: set[str] | None = None, sets: set[str] | None = None,
         since: str | None = None, force_download: bool = False, db_path: Path | None = None,
         bulk_file: Path | None = None) -> dict[str, Any]:
    path = bulk_file or download_bulk(source, force=force_download)
    conn = connect(db_path)
    init_schema(conn)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    placeholders = ",".join("?" * len(CARD_COLUMNS))
    upsert = f"INSERT OR REPLACE INTO cards ({','.join(CARD_COLUMNS)}) VALUES ({placeholders})"
    t0 = time.time()
    n = skipped = 0
    batch: list[tuple[Any, ...]] = []
    name_batch: list[tuple[str, str]] = []
    ids_batch: list[tuple[str]] = []

    def flush() -> None:
        conn.executemany("DELETE FROM card_names WHERE card_id = ?", ids_batch)
        conn.executemany(upsert, batch)
        conn.executemany("INSERT INTO card_names (card_id, name_norm) VALUES (?, ?)", name_batch)
        conn.commit()
        batch.clear(); name_batch.clear(); ids_batch.clear()

    conn.execute("BEGIN")
    for card in iter_cards(path):
        if not _keep(card, langs, sets, since):
            skipped += 1
            continue
        row, names = card_to_row(card, now)
        batch.append(row)
        ids_batch.append((card["id"],))
        name_batch.extend((card["id"], nm) for nm in names)
        n += 1
        if len(batch) >= 5000:
            flush()
            conn.execute("BEGIN")
            print(f"[sync] {n:,} cards ingested ...", flush=True)
    flush()
    meta = {
        "source": source, "bulk_file": path.name, "synced_at": now, "langs": ",".join(sorted(langs or [])),
        "sets": ",".join(sorted(sets or [])), "since": since or "", "ingested": str(n),
    }
    conn.executemany("INSERT OR REPLACE INTO sync_meta (key, value) VALUES (?, ?)", list(meta.items()))
    conn.commit()
    conn.execute("ANALYZE")
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
    conn.close()
    dt = time.time() - t0
    print(f"[sync] done: {n:,} ingested, {skipped:,} skipped, {total:,} total rows, {dt:.1f}s")
    return {"ingested": n, "skipped": skipped, "total": total, "seconds": dt}


def refresh_prices(db_path: Path | None = None, bulk_file: Path | None = None) -> dict[str, Any]:
    """Re-download default_cards (≈80 MB gz) and update only price columns of existing rows."""
    path = bulk_file or download_bulk("default_cards", force=True)
    conn = connect(db_path)
    init_schema(conn)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.time()
    rows: list[tuple[Any, ...]] = []
    for card in iter_cards(path):
        p = card.get("prices") or {}
        rows.append((_price(p.get("usd")), _price(p.get("usd_foil")), _price(p.get("usd_etched")), now, card["id"]))
    conn.execute("BEGIN")
    conn.executemany("UPDATE cards SET usd=?, usd_foil=?, usd_etched=?, updated_at=? WHERE id=?", rows)
    conn.execute("INSERT OR REPLACE INTO sync_meta (key, value) VALUES ('prices_refreshed_at', ?)", (now,))
    conn.commit()
    conn.close()
    dt = time.time() - t0
    print(f"[prices] refreshed {len(rows):,} price rows in {dt:.1f}s")
    return {"updated": len(rows), "seconds": dt}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Scryfall bulk mirror for BinderScan MTG")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync", help="download + ingest bulk data")
    s.add_argument("--source", default="default_cards", choices=["default_cards", "all_cards"])
    s.add_argument("--langs", default="", help="comma list, e.g. en,es (all_cards only; default: all in file)")
    s.add_argument("--sets", default="", help="comma list of set codes to keep")
    s.add_argument("--since", default="", help="keep printings released on/after YYYY-MM-DD")
    s.add_argument("--recent-sets", type=int, default=0, help="shortcut: keep printings from the last N months")
    s.add_argument("--force-download", action="store_true")
    s.add_argument("--bulk-file", type=Path, default=None, help="ingest a local bulk file instead of downloading")
    p = sub.add_parser("prices", help="fast price refresh")
    p.add_argument("--bulk-file", type=Path, default=None)
    args = ap.parse_args(argv)

    if args.cmd == "sync":
        since = args.since or None
        if args.recent_sets:
            d = datetime.now(timezone.utc)
            m = d.month - args.recent_sets
            y = d.year + (m - 1) // 12
            m = (m - 1) % 12 + 1
            since = f"{y:04d}-{m:02d}-01"
        langs = {x.strip() for x in args.langs.split(",") if x.strip()} or None
        if args.source == "all_cards" and not langs:
            langs = {"en", "es"}
            print("[sync] all_cards without --langs: defaulting to en,es")
        sets = {x.strip().lower() for x in args.sets.split(",") if x.strip()} or None
        sync(args.source, langs, sets, since, args.force_download, bulk_file=args.bulk_file)
    elif args.cmd == "prices":
        refresh_prices(bulk_file=args.bulk_file)
    return 0


if __name__ == "__main__":
    sys.exit(main())
