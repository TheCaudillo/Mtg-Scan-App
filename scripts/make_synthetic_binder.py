#!/usr/bin/env python3
"""Build synthetic binder-page test photos from real Scryfall card images.

Writes to services/scanner/tests/fixtures/:
  binder_flat.jpg        straight-on 3x3 page + partial cards peeking from both edges
  binder_angled.jpg      same page, perspective-warped with a glare blob
  binder_whatsapp.jpg    angled page inside a WhatsApp-style phone screenshot
  binder_manifest.json   ground truth (slot -> scryfall id)
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import _bootstrap  # noqa: F401
import cv2
import httpx
import numpy as np

from scanner.config import get_settings
from scanner.db import ScryfallDB

OUT = Path(__file__).resolve().parents[1] / "services" / "scanner" / "tests" / "fixtures"
PRINTINGS = [  # (set, collector number)
    ("mid", "10"),    # Cathar Commando (same-art reprint case)
    ("mom", "265"),   # Sword of Once and Future
    ("ori", "195"),   # Reclaim
    ("m11", "149"),   # Lightning Bolt
    ("cmr", "472"),   # Sol Ring
    ("dom", "168"),   # Llanowar Elves
    ("2xm", "107"),   # Thoughtseize
    ("sta", "10"),    # Swords to Plowshares (mystical archive)
    ("neo", "50"),    # Tamiyo's Safekeeping? (whatever is there)
]
EDGE_PRINTINGS = [("mh2", "198"), ("woe", "1")]
CW, CH = 488, 680


def fetch(db: ScryfallDB, set_code: str, cn: str, cache: Path) -> tuple[np.ndarray, str, str]:
    rows = db.by_set_cn(set_code, cn, lang="en")
    if not rows:
        raise SystemExit(f"{set_code} {cn} not in DB — run the Scryfall sync first")
    card = rows[0]
    path = cache / f"{card.id}.jpg"
    if not path.exists():
        r = httpx.get(card.image_normal, headers={"User-Agent": get_settings().user_agent}, timeout=30)
        r.raise_for_status()
        path.write_bytes(r.content)
    img = cv2.imread(str(path))
    return cv2.resize(img, (CW, CH)), card.id, card.name


def round_corners(img: np.ndarray, r: int = 18) -> np.ndarray:
    mask = np.zeros(img.shape[:2], np.uint8)
    h, w = mask.shape
    cv2.rectangle(mask, (r, 0), (w - r, h), 255, -1)
    cv2.rectangle(mask, (0, r), (w, h - r), 255, -1)
    for cx, cy in ((r, r), (w - r, r), (r, h - r), (w - r, h - r)):
        cv2.circle(mask, (cx, cy), r, 255, -1)
    return mask


def compose_page(cards: list[np.ndarray], edge: list[np.ndarray]) -> tuple[np.ndarray, list[list[float]]]:
    gap, margin = 34, 70
    W = margin * 2 + 3 * CW + 2 * gap
    H = margin * 2 + 3 * CH + 2 * gap
    rng = np.random.default_rng(7)
    page = np.full((H, W, 3), (38, 36, 40), np.uint8)
    page = cv2.add(page, rng.integers(0, 10, page.shape, dtype=np.uint8))
    boxes = []
    for i, img in enumerate(cards):
        r, c = divmod(i, 3)
        x = margin + c * (CW + gap)
        y = margin + r * (CH + gap)
        # sleeve pocket (slightly lighter, larger)
        cv2.rectangle(page, (x - 12, y - 12), (x + CW + 12, y + CH + 12), (70, 68, 74), -1)
        mask = round_corners(img)
        roi = page[y:y + CH, x:x + CW]
        roi[mask > 0] = img[mask > 0]
        boxes.append([x, y, x + CW, y + CH])
    # partial cards peeking from adjacent pages (cut by the image edge)
    canvas = np.full((H, W + 2 * 150, 3), (30, 28, 30), np.uint8)
    canvas[:, 150:150 + W] = page
    left, right = edge
    canvas[margin + 200:margin + 200 + CH, 0:150] = left[:, CW - 150:]
    canvas[margin + 500:margin + 500 + CH, 150 + W:] = right[:, :150]
    boxes = [[b[0] + 150, b[1], b[2] + 150, b[3]] for b in boxes]
    return canvas, boxes


def perspective(img: np.ndarray, boxes: list[list[float]]) -> tuple[np.ndarray, list[list[list[float]]]]:
    h, w = img.shape[:2]
    src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
    dst = np.float32([[w * 0.06, h * 0.04], [w * 0.95, 0], [w, h * 0.97], [0, h]])
    M = cv2.getPerspectiveTransform(src, dst)
    out = cv2.warpPerspective(img, M, (w, h), borderValue=(25, 25, 25))
    quads = []
    for x0, y0, x1, y1 in boxes:
        pts = np.float32([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]).reshape(-1, 1, 2)
        quads.append(cv2.perspectiveTransform(pts, M).reshape(4, 2).tolist())
    # glare blob
    glare = np.zeros((h, w), np.float32)
    cv2.ellipse(glare, (int(w * 0.62), int(h * 0.35)), (int(w * 0.10), int(h * 0.05)), 30, 0, 360, 1.0, -1)
    glare = cv2.GaussianBlur(glare, (0, 0), 40)[..., None]
    out = np.clip(out.astype(np.float32) + glare * 170, 0, 255).astype(np.uint8)
    return out, quads


def whatsapp(photo: np.ndarray, quads: list[list[list[float]]]) -> tuple[np.ndarray, list[list[list[float]]]]:
    SW, SH = 1080, 2340
    screen = np.zeros((SH, SW, 3), np.uint8)
    cv2.rectangle(screen, (0, 0), (SW, 90), (0, 0, 0), -1)  # status bar
    cv2.putText(screen, "9:41", (40, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 3)
    cv2.rectangle(screen, (0, 90), (SW, 260), (52, 44, 31), -1)  # header (#1F2C34 in BGR)
    cv2.circle(screen, (110, 175), 50, (180, 160, 140), -1)
    cv2.putText(screen, "Juan (Cartas MTG)", (190, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (240, 240, 240), 3)
    cv2.rectangle(screen, (0, SH - 230), (SW, SH), (52, 44, 31), -1)  # footer
    cv2.rectangle(screen, (30, SH - 180), (SW - 170, SH - 80), (70, 60, 45), -1)
    cv2.putText(screen, "Mensaje", (70, SH - 115), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (150, 150, 150), 3)
    cv2.circle(screen, (SW - 85, SH - 130), 55, (100, 168, 0), -1)
    h, w = photo.shape[:2]
    s = SW / w
    ph = int(h * s)
    small = cv2.resize(photo, (SW, ph), interpolation=cv2.INTER_AREA)
    y0 = 260 + (SH - 230 - 260 - ph) // 2
    screen[y0:y0 + ph] = small
    quads = [[[x * s, y * s + y0] for x, y in q] for q in quads]
    return screen, quads


def main() -> int:
    db = ScryfallDB()
    cache = get_settings().data_dir / "fixture_cache"
    cache.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    cards, ids, names = [], [], []
    for s, cn in PRINTINGS:
        img, cid, name = fetch(db, s, cn, cache)
        cards.append(img); ids.append(cid); names.append(name)
    edge = [fetch(db, s, cn, cache)[0] for s, cn in EDGE_PRINTINGS]
    page, boxes = compose_page(cards, edge)
    cv2.imwrite(str(OUT / "binder_flat.jpg"), page, [cv2.IMWRITE_JPEG_QUALITY, 85])
    angled, quads = perspective(page, boxes)
    cv2.imwrite(str(OUT / "binder_angled.jpg"), angled, [cv2.IMWRITE_JPEG_QUALITY, 85])
    wa, wquads = whatsapp(angled, quads)
    cv2.imwrite(str(OUT / "binder_whatsapp.jpg"), wa, [cv2.IMWRITE_JPEG_QUALITY, 80])
    manifest = {
        "slots": [{"slot": i + 1, "scryfall_id": ids[i], "name": names[i]} for i in range(9)],
        "flat_boxes": boxes, "angled_quads": quads, "whatsapp_quads": wquads,
    }
    (OUT / "binder_manifest.json").write_text(json.dumps(manifest, indent=1))
    print("wrote fixtures to", OUT)
    for sl in manifest["slots"]:
        print(f"  slot {sl['slot']}: {sl['name']}")
    return 0


if __name__ == "__main__":
    random.seed(0)
    sys.exit(main())
