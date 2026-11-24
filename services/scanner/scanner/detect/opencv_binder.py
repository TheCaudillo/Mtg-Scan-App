"""OpenCV binder-page detector.

Pipeline:
  1. strip screenshot UI chrome (WhatsApp bars, letterboxing)
  2. find card-shaped quads with several edge/threshold maps (cards in sleeves are messy)
  3. keep the dominant size/orientation cluster, drop nested boxes (art boxes) and
     partial cards peeking in from the left/right edge (adjacent binder page)
  4. fill holes in the observed rows×cols lattice (glare can hide a card edge)
  5. fall back to a uniform 3×3 grid when almost nothing is found
A manual grid from the UI bypasses 2–5 entirely.
"""
from __future__ import annotations

from typing import Optional

import cv2
import numpy as np

from .base import CardDetector, DetectedCard, DetectionResult
from .chrome import strip_chrome
from .crops import texture_score, warp_card
from .grid import center, grid_quads, iou_rect, order_cards, order_quad, quad_size

CARD_RATIO = 63 / 88  # 0.716
PROC_MAX = 1600


class OpenCVBinderDetector(CardDetector):
    name = "opencv"

    def __init__(self, min_cards_for_lattice: int = 3, ratio_tol: float = 0.12):
        self.min_cards_for_lattice = min_cards_for_lattice
        self.ratio_tol = ratio_tol

    # ------------------------------------------------------------------------------------------
    def detect(self, image: np.ndarray, grid: Optional[dict] = None) -> DetectionResult:
        H, W = image.shape[:2]
        if grid:
            corners = np.array([[p["x"], p["y"]] if isinstance(p, dict) else p for p in grid["corners"]], np.float32)
            quads = grid_quads(corners, int(grid.get("rows", 3)), int(grid.get("cols", 3)))
            cards = [DetectedCard(quad=q, score=1.0) for q in quads]
            return DetectionResult(order_cards(cards), "manual_grid", (0, 0, W, H))

        (cx, cy, cw, ch), chrome = strip_chrome(image)
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

        # back to original page coordinates
        for c in cards:
            c.quad = (c.quad / scale + np.array([cx, cy], np.float32)).astype(np.float32)
        return DetectionResult(order_cards(cards), method, (cx, cy, cw, ch), chrome,
                               debug={"candidates": len(cands)})

    # ------------------------------------------------------------------------------------------
    def _edge_maps(self, img: np.ndarray) -> list[np.ndarray]:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blur = cv2.bilateralFilter(gray, 7, 50, 50)
        maps = []
        med = float(np.median(blur))
        for lo_f, hi_f in ((0.66, 1.33), (0.33, 1.0)):
            e = cv2.Canny(blur, int(max(0, lo_f * med)), int(min(255, hi_f * med + 30)))
            e = cv2.morphologyEx(e, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)
            maps.append(e)
        # dark card borders vs lighter sleeves / binder: adaptive threshold
        th = cv2.adaptiveThreshold(blur, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 51, 7)
        maps.append(cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)))
        # Otsu on saturation separates colourful card faces from grey/black pages
        sat = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)[:, :, 1]
        _, ts = cv2.threshold(cv2.GaussianBlur(sat, (5, 5), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        maps.append(cv2.morphologyEx(ts, cv2.MORPH_OPEN, np.ones((7, 7), np.uint8)))
        return maps

    def _candidates(self, img: np.ndarray) -> list[DetectedCard]:
        h, w = img.shape[:2]
        area_img = h * w
        out: list[DetectedCard] = []
        for m in self._edge_maps(img):
            contours, _ = cv2.findContours(m, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                a = cv2.contourArea(cnt)
                if a < area_img / 80 or a > area_img / 2.2:
                    continue
                rect = cv2.minAreaRect(cnt)
                rw, rh = rect[1]
                if rw < 10 or rh < 10:
                    continue
                ratio = min(rw, rh) / max(rw, rh)
                if abs(ratio - CARD_RATIO) > self.ratio_tol:
                    continue
                rectangularity = a / (rw * rh)
                if rectangularity < 0.80:
                    continue
                peri = cv2.arcLength(cnt, True)
                approx = cv2.approxPolyDP(cnt, 0.02 * peri, True)
                if len(approx) == 4 and cv2.isContourConvex(approx):
                    quad = order_quad(approx.reshape(4, 2))
                else:
                    quad = order_quad(cv2.boxPoints(rect))
                score = rectangularity * (1 - abs(ratio - CARD_RATIO) / self.ratio_tol * 0.5)
                out.append(DetectedCard(quad=quad.astype(np.float32), score=float(score)))
        return out

    def _filter(self, cands: list[DetectedCard], shape: tuple[int, int]) -> list[DetectedCard]:
        if not cands:
            return []
        h, w = shape
        # dominant orientation
        portrait = [c for c in cands if quad_size(c.quad)[1] >= quad_size(c.quad)[0]]
        landscape = [c for c in cands if quad_size(c.quad)[1] < quad_size(c.quad)[0]]
        cands = portrait if len(portrait) >= len(landscape) else landscape
        # dominant size: largest cluster of areas within ±35% of each other, preferring larger sizes
        areas = np.array([np.prod(quad_size(c.quad)) for c in cands])
        best_ref, best_n = None, -1
        for a in sorted(set(np.round(areas, -1)), reverse=True):
            n = int(np.sum((areas > a * 0.65) & (areas < a * 1.35)))
            if n > best_n:
                best_ref, best_n = a, n
        keep = [c for c, a in zip(cands, areas) if best_ref * 0.65 < a < best_ref * 1.35]
        # NMS: merge duplicates found by several maps; drop boxes nested in another kept box
        keep.sort(key=lambda c: (-np.prod(quad_size(c.quad)) * c.score))
        final: list[DetectedCard] = []
        for c in keep:
            dup = False
            for f in final:
                iou, contain = iou_rect(c.quad, f.quad)
                if iou > 0.35 or contain > 0.6:
                    dup = True
                    break
            if not dup:
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
        margin_x = 0.012 * w
        cw, ch = quad_size(c.quad)
        touches_lr = x0 <= margin_x or x1 >= w - margin_x
        touches_tb = y0 <= 0.012 * h or y1 >= h - 0.012 * h
        if touches_lr and cw < 0.88 * mw:
            return True
        if touches_tb and ch < 0.88 * mh:
            return True
        return False

    def _fill_lattice(self, cards: list[DetectedCard], img: np.ndarray) -> list[DetectedCard]:
        """Infer missing cells inside the observed rows×cols lattice using a local affine model."""
        ordered = order_cards(list(cards))
        nrows = max(c.row for c in ordered) + 1
        ncols = max(c.col for c in ordered) + 1
        if nrows * ncols <= len(ordered) or nrows * ncols > 24:
            return ordered
        # least squares: corner_k(row, col) = A_k @ [col, row, 1]
        X = np.array([[c.col, c.row, 1.0] for c in ordered])
        models = []
        for k in range(4):
            Y = np.array([c.quad[k] for c in ordered])
            sol, *_ = np.linalg.lstsq(X, Y, rcond=None)
            models.append(sol)
        have = {(c.row, c.col) for c in ordered}
        h, w = img.shape[:2]
        textures = [texture_score(warp_card(img, c.quad)) for c in ordered[:6]]
        tex_ref = float(np.median(textures)) if textures else 0.0
        out = list(ordered)
        for r in range(nrows):
            for col in range(ncols):
                if (r, col) in have:
                    continue
                quad = np.array([np.array([col, r, 1.0]) @ models[k] for k in range(4)], np.float32)
                if quad[:, 0].min() < -0.02 * w or quad[:, 0].max() > 1.02 * w or quad[:, 1].min() < -0.02 * h or quad[:, 1].max() > 1.02 * h:
                    continue
                quad[:, 0] = np.clip(quad[:, 0], 0, w - 1)
                quad[:, 1] = np.clip(quad[:, 1], 0, h - 1)
                tex = texture_score(warp_card(img, quad))
                if tex_ref and tex < 0.15 * tex_ref:
                    continue  # empty pocket
                out.append(DetectedCard(quad=quad, score=0.5, inferred=True))
        return out

    def _uniform_grid(self, img: np.ndarray, rows: int = 3, cols: int = 3) -> list[DetectedCard]:
        h, w = img.shape[:2]
        # fit a card-ratio grid centred in the content area
        cell_h = h / rows
        cell_w = cell_h * CARD_RATIO
        if cell_w * cols > w:
            cell_w = w / cols
            cell_h = cell_w / CARD_RATIO
        gw, gh = cell_w * cols, cell_h * rows
        x0, y0 = (w - gw) / 2, (h - gh) / 2
        corners = np.array([[x0, y0], [x0 + gw, y0], [x0 + gw, y0 + gh], [x0, y0 + gh]], np.float32)
        return [DetectedCard(quad=q, score=0.2, inferred=True) for q in grid_quads(corners, rows, cols, gutter=0.03)]
