"""OpenCV binder-page detector.

Pipeline:
  1. try the photo as-is and with screenshot UI chrome stripped (WhatsApp bars); keep the better
  2. find card-shaped quads from several maps: edges, adaptive thresholds, and a filled
     "card face" mask (bright/saturated faces vs dark pockets, holes filled so dark art stays whole)
  3. accept perspective-squashed shapes (phone photos are rarely straight-on), keep the dominant
     size cluster, drop nested boxes and partial cards cut by the image edge (adjacent page)
  4. fill holes in the observed rows×cols lattice with a homography (perspective-aware),
     skipping empty pockets
  5. if almost nothing is found, fall back to a uniform 3×3 guess (flagged for review / grid overlay)
A manual grid or manual boxes from the UI bypass all of this.
"""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from .base import CardDetector, DetectedCard, DetectionResult
from .chrome import strip_chrome
from .crops import warp_card
from .grid import grid_quads, iou_rect, order_cards, order_quad, quad_size

CARD_RATIO = 63 / 88  # 0.716 width/height seen straight on
# width/height of a portrait card in a photo: narrower when tilted sideways, wider when the
# phone is tilted top-to-bottom (foreshortening squashes height) — real binder shots reach ~1.1
MIN_WH, MAX_WH = 0.55, 1.22
PROC_MAX = 1600


def _fill_holes(m: np.ndarray) -> np.ndarray:
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = np.zeros_like(m)
    cv2.drawContours(out, cs, -1, 255, -1)
    return out


class OpenCVBinderDetector(CardDetector):
    name = "opencv"

    def __init__(self, min_cards_for_lattice: int = 2):
        self.min_cards_for_lattice = min_cards_for_lattice

    # ------------------------------------------------------------------------------------------
    def detect(self, image: np.ndarray, grid: Optional[dict] = None) -> DetectionResult:
        H, W = image.shape[:2]
        if grid:
            corners = np.array([[p["x"], p["y"]] if isinstance(p, dict) else p for p in grid["corners"]], np.float32)
            quads = grid_quads(corners, int(grid.get("rows", 3)), int(grid.get("cols", 3)))
            cards = [DetectedCard(quad=q, score=1.0) for q in quads]
            return DetectionResult(order_cards(cards), "manual_grid", (0, 0, W, H))

        # chrome stripping can misfire on real photos (flat black binder ≈ "UI bar"): try both
        box, chrome = strip_chrome(image)
        attempts = [self._detect_in(image, (0, 0, W, H), False)]
        if chrome:
            attempts.append(self._detect_in(image, box, True))
        best = max(attempts, key=lambda r: (r.method != "uniform_grid",
                                            sum(not c.inferred for c in r.cards), len(r.cards), r.chrome_cropped))
        return best

    def _detect_in(self, image: np.ndarray, box: tuple[int, int, int, int], chrome: bool) -> DetectionResult:
        cx, cy, cw, ch = box
        content = image[cy:cy + ch, cx:cx + cw]
        scale = min(1.0, PROC_MAX / max(cw, ch))
        work = cv2.resize(content, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else content

        cands = self._candidates(work)
        cards = self._filter(cands, work.shape[:2])
        method = "contours"
        if len(cards) >= self.min_cards_for_lattice:
            filled = self._fill_lattice(cards, work)
            if len(filled) > len(cards):
                method = "contours+lattice"
            cards = filled
        else:
            cards = self._uniform_grid(work)
            method = "uniform_grid"

        for c in cards:
            c.maybe_inner = self._maybe_inner_frame(work, c.quad)
            c.quad = (c.quad / scale + np.array([cx, cy], np.float32)).astype(np.float32)
        return DetectionResult(order_cards(cards), method, (cx, cy, cw, ch), chrome,
                               debug={"candidates": len(cands)})

    # ------------------------------------------------------------------------------------------
    def _maps(self, img: np.ndarray) -> list[np.ndarray]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.bilateralFilter(gray, 7, 50, 50)
        maps = []
        med = float(np.median(blur))
        for lo_f, hi_f in ((0.66, 1.33), (0.33, 1.0)):
            e = cv2.Canny(blur, int(max(0, lo_f * med)), int(min(255, hi_f * med + 30)))
            maps.append(cv2.morphologyEx(e, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2))
        th = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 51, 7)
        maps.append(cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)))
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        _, ts = cv2.threshold(cv2.GaussianBlur(hsv[:, :, 1], (5, 5), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        maps.append(cv2.morphologyEx(ts, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8)))
        # filled card-face masks: faces are bright or saturated, pockets/black borders are dark
        hsvb = cv2.cvtColor(cv2.GaussianBlur(img, (5, 5), 0), cv2.COLOR_BGR2HSV)
        k = max(5, int(min(img.shape[:2]) * 0.01) | 1)
        for vt, st in ((75, 70), (90, 80), (110, 90)):
            m = ((hsvb[:, :, 2] > vt) | ((hsvb[:, :, 1] > st) & (hsvb[:, :, 2] > 45))).astype(np.uint8) * 255
            m = _fill_holes(cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)))
            maps.append(cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((k, k), np.uint8)))  # cut bridges
        return maps

    def _candidates(self, img: np.ndarray) -> list[DetectedCard]:
        h, w = img.shape[:2]
        area_img = h * w
        out: list[DetectedCard] = []
        for m in self._maps(img):
            contours, _ = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                a = cv2.contourArea(cnt)
                if a < area_img / 120 or a > area_img / 3:
                    continue
                hull = cv2.convexHull(cnt)
                peri = cv2.arcLength(hull, True)
                approx = cv2.approxPolyDP(hull, 0.04 * peri, True)
                if len(approx) == 4:
                    quad = order_quad(approx.reshape(4, 2))  # keeps perspective (trapezoid)
                else:
                    quad = order_quad(cv2.boxPoints(cv2.minAreaRect(cnt)))
                qa = cv2.contourArea(quad.astype(np.float32))
                if qa <= 0 or a / qa < 0.82:
                    continue
                qw, qh = quad_size(quad)
                if qw < 10 or qh < 10:
                    continue
                wh = qw / qh
                if not (MIN_WH <= wh <= MAX_WH or MIN_WH <= 1 / wh <= MAX_WH):
                    continue
                # prefer shapes close to a straight-on card, but don't exclude squashed ones
                shape = 1.0 - min(abs(wh - CARD_RATIO), abs(1 / wh - CARD_RATIO)) * 0.5
                out.append(DetectedCard(quad=quad.astype(np.float32), score=float(min(1.0, a / qa) * shape)))
        return out

    def _filter(self, cands: list[DetectedCard], shape: tuple[int, int]) -> list[DetectedCard]:
        if not cands:
            return []
        h, w = shape
        portrait = [c for c in cands if quad_size(c.quad)[1] * MAX_WH >= quad_size(c.quad)[0]]
        landscape = [c for c in cands if quad_size(c.quad)[1] * MAX_WH < quad_size(c.quad)[0]]
        cands = portrait if len(portrait) >= len(landscape) else landscape
        # dominant size cluster; perspective makes far rows smaller, so the band is wide
        areas = np.array([np.prod(quad_size(c.quad)) for c in cands])
        best_ref, best_n = None, -1
        for a in sorted(set(np.round(areas, -1)), reverse=True):
            n = int(np.sum((areas > a * 0.5) & (areas < a * 1.6)))
            if n > best_n:
                best_ref, best_n = a, n
        keep = [c for c, a in zip(cands, areas) if best_ref * 0.45 < a < best_ref * 1.9]
        # NMS: same card found by several maps; drop boxes nested inside a kept one (art boxes)
        # shape/fill quality first; size only breaks near-ties (bigger boxes tend to include sleeve)
        keep.sort(key=lambda c: -(c.score + 0.1 * np.prod(quad_size(c.quad)) / best_ref))
        final: list[DetectedCard] = []
        for c in keep:
            if any(iou > 0.3 or contain > 0.6 for iou, contain in (iou_rect(c.quad, f.quad) for f in final)):
                continue
            final.append(c)
        if not final:
            return []
        mw = float(np.median([quad_size(c.quad)[0] for c in final]))
        mh = float(np.median([quad_size(c.quad)[1] for c in final]))
        return [c for c in final if not self._is_partial_edge(c, w, h, mw, mh)]

    @staticmethod
    def _is_partial_edge(c: DetectedCard, w: int, h: int, mw: float, mh: float) -> bool:
        x0, y0 = c.quad.min(axis=0)
        x1, y1 = c.quad.max(axis=0)
        cw, ch = quad_size(c.quad)
        if (x0 <= 0.012 * w or x1 >= w - 0.012 * w) and cw < 0.85 * mw:
            return True
        if (y0 <= 0.012 * h or y1 >= h - 0.012 * h) and ch < 0.85 * mh:
            return True
        return False

    @staticmethod
    def _maybe_inner_frame(img: np.ndarray, quad: np.ndarray) -> bool:
        """True if no black border shows just inside the box: it may hug the coloured frame inside
        the border (sleeved cards) — or be a borderless/white-border card. The matcher decides."""
        hsv = cv2.cvtColor(warp_card(img, quad), cv2.COLOR_BGR2HSV)
        h, w = hsv.shape[:2]
        bw, bh = max(2, int(w * 0.025)), max(2, int(h * 0.018))
        rings = [hsv[:bh, bw:-bw], hsv[-bh:, bw:-bw], hsv[bh:-bh, :bw], hsv[bh:-bh, -bw:]]
        return sum(float(np.median(r[:, :, 2])) < 85 for r in rings) < 3

    @staticmethod
    def _face_fraction(img: np.ndarray, quad: np.ndarray) -> float:
        """Share of bright/saturated pixels — card faces are high, empty black pockets low."""
        hsv = cv2.cvtColor(warp_card(img, quad), cv2.COLOR_BGR2HSV)
        return float(((hsv[:, :, 2] > 90) | ((hsv[:, :, 1] > 80) & (hsv[:, :, 2] > 45))).mean())

    def _fill_lattice(self, cards: list[DetectedCard], img: np.ndarray) -> list[DetectedCard]:
        """Infer missed cells inside the observed rows×cols lattice with a homography."""
        ordered = order_cards(list(cards))
        nrows = max(c.row for c in ordered) + 1
        ncols = max(c.col for c in ordered) + 1
        if nrows * ncols <= len(ordered) or nrows * ncols > 24:
            return ordered
        g = 0.05  # card inset within its grid cell
        src, dst = [], []
        for c in ordered:
            r, k = c.row, c.col
            src += [[k + g, r + g], [k + 1 - g, r + g], [k + 1 - g, r + 1 - g], [k + g, r + 1 - g]]
            dst += list(c.quad)
        src_a, dst_a = np.array(src, np.float32), np.array(dst, np.float32)
        if len(ordered) >= 2 and nrows > 1 and ncols > 1:
            Hm, _ = cv2.findHomography(src_a, dst_a, cv2.RANSAC, 0.12 * float(np.median([quad_size(c.quad)[0] for c in ordered])))
        else:
            Hm = None
        if Hm is None:
            A, _ = cv2.estimateAffine2D(src_a, dst_a)
            if A is None:
                return ordered
            Hm = np.vstack([A, [0, 0, 1]])
        h, w = img.shape[:2]
        face_ref = float(np.median([self._face_fraction(img, c.quad) for c in ordered]))
        have = {(c.row, c.col) for c in ordered}
        out = list(ordered)
        for r in range(nrows):
            for k in range(ncols):
                if (r, k) in have:
                    continue
                cell = np.array([[k + g, r + g], [k + 1 - g, r + g], [k + 1 - g, r + 1 - g], [k + g, r + 1 - g]], np.float32)
                quad = cv2.perspectiveTransform(cell.reshape(-1, 1, 2), Hm).reshape(4, 2)
                if quad[:, 0].min() < -0.02 * w or quad[:, 0].max() > 1.02 * w or quad[:, 1].min() < -0.02 * h or quad[:, 1].max() > 1.02 * h:
                    continue
                quad[:, 0] = np.clip(quad[:, 0], 0, w - 1)
                quad[:, 1] = np.clip(quad[:, 1], 0, h - 1)
                if self._face_fraction(img, quad) < 0.45 * face_ref:
                    continue  # empty pocket
                out.append(DetectedCard(quad=quad.astype(np.float32), score=0.5, inferred=True))
        return out

    def _uniform_grid(self, img: np.ndarray, rows: int = 3, cols: int = 3) -> list[DetectedCard]:
        h, w = img.shape[:2]
        cell_h = h / rows
        cell_w = cell_h * CARD_RATIO
        if cell_w * cols > w:
            cell_w = w / cols
            cell_h = cell_w / CARD_RATIO
        gw, gh = cell_w * cols, cell_h * rows
        x0, y0 = (w - gw) / 2, (h - gh) / 2
        corners = np.array([[x0, y0], [x0 + gw, y0], [x0 + gw, y0 + gh], [x0, y0 + gh]], np.float32)
        return [DetectedCard(quad=q, score=0.2, inferred=True) for q in grid_quads(corners, rows, cols, gutter=0.03)]
