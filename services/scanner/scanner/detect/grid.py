"""Geometry helpers: quad ordering, row/col assignment, lattice filling, manual grids."""
from __future__ import annotations

import numpy as np

from .base import DetectedCard


def order_quad(pts: np.ndarray) -> np.ndarray:
    """Order 4 points as tl, tr, br, bl."""
    pts = np.asarray(pts, dtype=np.float32).reshape(4, 2)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    out = np.zeros((4, 2), np.float32)
    out[0] = pts[np.argmin(s)]
    out[2] = pts[np.argmax(s)]
    out[1] = pts[np.argmin(d)]
    out[3] = pts[np.argmax(d)]
    return out


def quad_size(q: np.ndarray) -> tuple[float, float]:
    w = (np.linalg.norm(q[1] - q[0]) + np.linalg.norm(q[2] - q[3])) / 2
    h = (np.linalg.norm(q[3] - q[0]) + np.linalg.norm(q[2] - q[1])) / 2
    return float(w), float(h)


def center(q: np.ndarray) -> np.ndarray:
    return q.mean(axis=0)


def order_cards(cards: list[DetectedCard]) -> list[DetectedCard]:
    """Assign row/col/slot reading order (top→bottom, left→right)."""
    if not cards:
        return cards
    hs = [quad_size(c.quad)[1] for c in cards]
    ws = [quad_size(c.quad)[0] for c in cards]
    mh, mw = float(np.median(hs)), float(np.median(ws))
    by_y = sorted(cards, key=lambda c: center(c.quad)[1])
    rows: list[list[DetectedCard]] = []
    for c in by_y:
        cy = center(c.quad)[1]
        if rows and abs(np.mean([center(r.quad)[1] for r in rows[-1]]) - cy) < 0.5 * mh:
            rows[-1].append(c)
        else:
            rows.append([c])
    # global column positions so a row missing its first card still gets col=1
    xs = sorted(center(c.quad)[0] for c in cards)
    col_centers: list[float] = []
    for x in xs:
        if col_centers and abs(x - col_centers[-1]) < 0.5 * mw:
            col_centers[-1] = (col_centers[-1] + x) / 2
        else:
            col_centers.append(x)
    ordered: list[DetectedCard] = []
    for ri, row in enumerate(rows):
        for c in sorted(row, key=lambda c: center(c.quad)[0]):
            cx = center(c.quad)[0]
            c.row = ri
            c.col = int(np.argmin([abs(cx - k) for k in col_centers]))
            ordered.append(c)
    ncols = max(len(col_centers), 1)
    for c in ordered:
        c.slot = c.row * ncols + c.col + 1
    return ordered


def grid_quads(corners: np.ndarray, rows: int, cols: int, gutter: float = 0.02) -> list[np.ndarray]:
    """Split a (possibly perspective) quad into rows×cols cell quads via bilinear interpolation."""
    tl, tr, br, bl = order_quad(corners)

    def lerp(u: float, v: float) -> np.ndarray:
        top = tl + (tr - tl) * u
        bot = bl + (br - bl) * u
        return top + (bot - top) * v

    out = []
    for r in range(rows):
        for c in range(cols):
            u0, u1 = (c + gutter) / cols, (c + 1 - gutter) / cols
            v0, v1 = (r + gutter) / rows, (r + 1 - gutter) / rows
            out.append(np.array([lerp(u0, v0), lerp(u1, v0), lerp(u1, v1), lerp(u0, v1)], np.float32))
    return out


def iou_rect(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """IoU and containment (inter / smaller area) of the axis-aligned bounds of two quads."""
    ax0, ay0 = a.min(axis=0); ax1, ay1 = a.max(axis=0)
    bx0, by0 = b.min(axis=0); bx1, by1 = b.max(axis=0)
    iw = max(0.0, min(ax1, bx1) - max(ax0, bx0))
    ih = max(0.0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    aa = (ax1 - ax0) * (ay1 - ay0)
    ba = (bx1 - bx0) * (by1 - by0)
    union = aa + ba - inter
    return (inter / union if union else 0.0), (inter / min(aa, ba) if min(aa, ba) else 0.0)
