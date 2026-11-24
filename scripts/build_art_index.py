#!/usr/bin/env python3
"""Resumable OpenCLIP → FAISS art index builder (Mode A).

One vector per unique artwork (illustration_id) using Scryfall `art_crop` images.
Safe to Ctrl-C and re-run: finished shards in data/art_index/shards are skipped.

    python scripts/build_art_index.py                     # all unique artworks (~45k, ~40-60 min CPU)
    python scripts/build_art_index.py --since 2020-01-01  # quick partial index
    python scripts/build_art_index.py --sets mid,inr,fdn
    python scripts/build_art_index.py --finalize-only     # rebuild index.faiss from shards
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import _bootstrap  # noqa: F401
import httpx
import numpy as np
from PIL import Image

from scanner.config import get_settings
from scanner.db import ScryfallDB

SHARD = 256


def targets(db: ScryfallDB, sets: set[str] | None, since: str | None, limit: int | None) -> list[tuple[str, str, str]]:
    """One representative printing per illustration. Prefer what people actually hold in binders:
    modern/standard frame, black border, not full-art/borderless/extended/showcase, not Secret Lair or promo
    (those crop the same artwork differently)."""
    where = ["lang='en'", "illustration_id IS NOT NULL", "image_art_crop IS NOT NULL"]
    params: list = []
    if sets:
        where.append(f"set_code IN ({','.join('?' * len(sets))})")
        params += sorted(sets)
    if since:
        where.append("released_at >= ?")
        params.append(since)
    sql = f"""
        SELECT illustration_id, id, image_art_crop FROM (
          SELECT illustration_id, id, image_art_crop, released_at,
                 ROW_NUMBER() OVER (PARTITION BY illustration_id ORDER BY
                   (border_color != 'black'), full_art,
                   (frame_effects LIKE '%extendedart%' OR frame_effects LIKE '%showcase%'),
                   (frame NOT IN ('2015', '2003')), (set_code = 'sld'), promo, released_at DESC) AS rn
          FROM cards WHERE {' AND '.join(where)}
        ) WHERE rn = 1 ORDER BY released_at DESC"""
    out = [(r[0], r[1], r[2]) for r in db.conn.execute(sql, params).fetchall()]
    return out[:limit] if limit else out


def finalize(index_dir: Path) -> int:
    import faiss

    shards = sorted(p for p in (index_dir / "shards").glob("*.npz") if ".tmp" not in p.name)
    if not shards:
        print("[index] no shards yet")
        return 0
    latest: dict[str, tuple[np.ndarray, str]] = {}  # later shards override earlier (representative refresh)
    for s in shards:
        try:
            z = np.load(s, allow_pickle=False)
            rows = list(zip(z["emb"], z["ill"], z["cid"]))
        except Exception as e:  # noqa: BLE001 — shard still being written by a concurrent run
            print(f"[index] skipping unreadable shard {s.name}: {e}")
            continue
        for e, ill, cid in rows:
            latest[str(ill)] = (e, str(cid))
    ids = [{"illustration_id": ill, "card_id": cid} for ill, (_, cid) in latest.items()]
    mat = np.stack([e for e, _ in latest.values()]).astype(np.float32)
    index = faiss.IndexFlatIP(mat.shape[1])
    index.add(mat)
    tmp = index_dir / "index.faiss.tmp"
    faiss.write_index(index, str(tmp))
    tmp.rename(index_dir / "index.faiss")
    (index_dir / "ids.json").write_text(json.dumps(ids))
    print(f"[index] wrote index.faiss with {index.ntotal:,} artworks (dim {mat.shape[1]})")
    return index.ntotal


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", default="")
    ap.add_argument("--since", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=16, help="parallel image downloads")
    ap.add_argument("--finalize-only", action="store_true")
    args = ap.parse_args()

    s = get_settings()
    index_dir = s.index_dir
    (index_dir / "shards").mkdir(parents=True, exist_ok=True)
    if args.finalize_only:
        finalize(index_dir)
        return 0

    db = ScryfallDB()
    sets = {x.strip().lower() for x in args.sets.split(",") if x.strip()} or None
    todo = targets(db, sets, args.since or None, args.limit or None)
    done: set[tuple[str, str]] = set()  # (illustration_id, representative card_id)
    for sh in sorted((index_dir / "shards").glob("*.npz")):
        if ".tmp" in sh.name:
            sh.unlink()
            continue
        try:
            z = np.load(sh)
            done.update(zip((str(x) for x in z["ill"]), (str(x) for x in z["cid"])))
        except Exception:  # noqa: BLE001 — truncated shard from an interrupted run: redo it
            sh.unlink()
    todo = [t for t in todo if (t[0], t[1]) not in done]
    print(f"[index] {len(done):,} artworks already embedded, {len(todo):,} to go (new or better representative)")
    if not todo:
        finalize(index_dir)
        return 0

    from scanner.match.clip_faiss import ClipEmbedder
    emb = ClipEmbedder.get()
    client = httpx.Client(headers={"User-Agent": s.user_agent}, timeout=30, follow_redirects=True,
                          limits=httpx.Limits(max_connections=args.workers))

    def fetch(t: tuple[str, str, str]):
        for attempt in range(3):
            try:
                r = client.get(t[2])
                r.raise_for_status()
                return Image.open(io.BytesIO(r.content)).convert("RGB")
            except Exception:  # noqa: BLE001
                time.sleep(1 + attempt)
        return None

    t0 = time.time()
    n_done = 0
    existing = [int(p.stem.split("_")[1].split(".")[0]) for p in (index_dir / "shards").glob("shard_*.npz")]
    shard_no = max(existing, default=-1) + 1
    with ThreadPoolExecutor(args.workers) as pool:
        for start in range(0, len(todo), SHARD):
            chunk = todo[start:start + SHARD]
            imgs = list(pool.map(fetch, chunk))
            keep = [(t, im) for t, im in zip(chunk, imgs) if im is not None]
            if not keep:
                continue
            vecs = np.concatenate([emb.embed_pil([im for _, im in keep[i:i + 64]]) for i in range(0, len(keep), 64)])
            tmp = index_dir / "shards" / f"shard_{shard_no:05d}.tmp.npz"
            np.savez(tmp, emb=vecs, ill=np.array([t[0] for t, _ in keep]), cid=np.array([t[1] for t, _ in keep]))
            tmp.rename(index_dir / "shards" / f"shard_{shard_no:05d}.npz")
            shard_no += 1
            n_done += len(keep)
            rate = n_done / (time.time() - t0)
            eta = (len(todo) - start - len(chunk)) / max(rate, 1e-6)
            print(f"[index] {n_done:,}/{len(todo):,}  {rate:5.1f} img/s  eta {eta / 60:5.1f} min", flush=True)
    finalize(index_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
