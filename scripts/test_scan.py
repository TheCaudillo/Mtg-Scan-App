#!/usr/bin/env python3
"""CLI smoke test: scan one binder photo end-to-end and print what was found.

    python scripts/test_scan.py path/to/binder.jpg
    python scripts/test_scan.py photo.jpg --grid 3x3 --debug out.jpg   # force uniform grid + draw boxes
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import tempfile
import time
from pathlib import Path

import _bootstrap  # noqa: F401
import cv2
import numpy as np

from scanner.db import ScryfallDB
from scanner.match import HybridMatcher
from scanner.pipeline import ScanPipeline, load_image


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path)
    ap.add_argument("--debug", type=Path, help="write an annotated copy of the photo")
    ap.add_argument("--grid", help="manual RxC grid over the full image, e.g. 3x3")
    args = ap.parse_args()

    db = ScryfallDB()
    if db.count() == 0:
        print("scryfall.db is empty — run: make sync")
        return 1
    matcher = HybridMatcher.from_settings(db)
    print("matcher:", matcher.describe())
    pipe = ScanPipeline(matcher)
    grid = None
    if args.grid:
        r, c = (int(x) for x in args.grid.lower().split("x"))
        img = load_image(args.image)
        h, w = img.shape[:2]
        grid = {"corners": [[0, 0], [w, 0], [w, h], [0, h]], "rows": r, "cols": c}

    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmp:
        det, cards = asyncio.run(pipe.scan_page(args.image, "cli", "page1", Path(tmp), "/tmp", grid=grid))
    dt = time.time() - t0
    print(f"\ndetected {len(cards)} cards via {det.method} (chrome stripped: {det.chrome_cropped}) in {dt:.2f}s\n")
    total = 0.0
    for c in cards:
        p = c.selected
        price = f"${c.unit_price_usd:7.2f}" if c.unit_price_usd is not None else "    N/A"
        if p:
            total += c.unit_price_usd or 0
            line = f"{p.name[:34]:34} {p.set_code.upper():6} #{p.collector_number:6} {c.finish:8} {c.lang} {price}"
        else:
            line = f"{'(unidentified)':34} {'':6}  {'':6} {'':8}    {price}"
        review = f"  REVIEW: {','.join(c.review_reasons)}" if c.needs_review else ""
        print(f"  slot {c.slot:2}  {line}  conf {c.confidence:.2f}  [{c.match_method}]{review}")
        if c.needs_review and len(c.candidates) > 1:
            print("           candidates: " + " | ".join(f"{x.set_code.upper()} #{x.collector_number}" for x in c.candidates))
    print(f"\nretail total (selected finishes): ${total:.2f}")

    if args.debug:
        img = load_image(args.image)
        for c in cards:
            q = np.array([[p.x, p.y] for p in c.quad], np.int32)
            color = (0, 200, 0) if c.status == "identified" else (0, 180, 255) if c.status == "needs_review" else (0, 0, 255)
            cv2.polylines(img, [q], True, color, 4)
            label = f"{c.slot}: {c.selected.name if c.selected else '?'}"
            cv2.putText(img, label[:28], tuple(q[0] + [8, 36]), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 3)
        cv2.imwrite(str(args.debug), img)
        print("annotated image:", args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
