"""Strip phone-screenshot UI chrome (WhatsApp header/footer bars, status bar, letterboxing).

Heuristic: UI bars are rows (or columns) where most pixels share one colour, even with a few
icons/labels on them. Photo content almost never is. We keep the largest contiguous run of
"content" rows/cols.
"""
from __future__ import annotations

import numpy as np

TOL = 14
FLAT_FRAC = 0.72


def _flatness(lines: np.ndarray) -> np.ndarray:
    """lines: (N, L, 3) → fraction of pixels in each line within TOL of that line's median colour."""
    med = np.median(lines, axis=1, keepdims=True)
    close = np.all(np.abs(lines.astype(np.int16) - med.astype(np.int16)) <= TOL, axis=2)
    return close.mean(axis=1)


def _content_span(flat: np.ndarray, min_frac: float = 0.35) -> tuple[int, int] | None:
    n = len(flat)
    win = max(3, n // 80)
    smooth = np.convolve(flat, np.ones(win) / win, mode="same")
    content = smooth < FLAT_FRAC
    best = (0, 0)
    start = None
    for i, c in enumerate(np.append(content, False)):
        if c and start is None:
            start = i
        elif not c and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    if best[1] - best[0] < n * min_frac:
        return None
    return best


def strip_chrome(image: np.ndarray) -> tuple[tuple[int, int, int, int], bool]:
    """Return content box (x, y, w, h) and whether anything meaningful was cropped."""
    h, w = image.shape[:2]
    scale = 600 / max(h, w)
    small = image if scale >= 1 else _resize(image, scale)
    sh, sw = small.shape[:2]
    rows = _content_span(_flatness(small))
    y0, y1 = rows if rows else (0, sh)
    cols = _content_span(_flatness(np.transpose(small[y0:y1], (1, 0, 2))))
    x0, x1 = cols if cols else (0, sw)
    inv = 1 / scale if scale < 1 else 1.0
    # pad slightly inward-safe: expand by 1% so we never shave a card border
    pad_y, pad_x = int(0.01 * h), int(0.01 * w)
    X0 = max(0, int(x0 * inv) - pad_x)
    Y0 = max(0, int(y0 * inv) - pad_y)
    X1 = min(w, int(x1 * inv) + pad_x)
    Y1 = min(h, int(y1 * inv) + pad_y)
    cropped = (Y0 > 0.03 * h) or (h - Y1 > 0.03 * h) or (X0 > 0.03 * w) or (w - X1 > 0.03 * w)
    if not cropped:
        return (0, 0, w, h), False
    return (X0, Y0, X1 - X0, Y1 - Y0), True


def _resize(img: np.ndarray, scale: float) -> np.ndarray:
    import cv2
    return cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
