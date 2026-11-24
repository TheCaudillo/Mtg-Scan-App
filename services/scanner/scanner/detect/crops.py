"""Deskew a detected quad to an upright card and cut the regions the matchers need."""
from __future__ import annotations

import cv2
import numpy as np

from .base import CardCrops
from .grid import order_quad, quad_size

CARD_W, CARD_H = 488, 680  # 63x88mm @ ~7.75 px/mm

# Regions as fractions of the upright card (x0, y0, x1, y1) — modern (2015+) frame
ART_BOX = (0.075, 0.110, 0.925, 0.555)
STRIP_BOX = (0.035, 0.912, 0.520, 0.980)  # rarity / collector no. / set / • ★ / language
SET_SYMBOL_BOX = (0.800, 0.555, 0.945, 0.625)
NAME_BAR_BOX = (0.055, 0.035, 0.800, 0.100)


def warp_card(image: np.ndarray, quad: np.ndarray) -> np.ndarray:
    q = order_quad(quad)
    w, h = quad_size(q)
    landscape = w > h * 1.1
    dw, dh = (CARD_H, CARD_W) if landscape else (CARD_W, CARD_H)
    dst = np.array([[0, 0], [dw - 1, 0], [dw - 1, dh - 1], [0, dh - 1]], np.float32)
    M = cv2.getPerspectiveTransform(q, dst)
    out = cv2.warpPerspective(image, M, (dw, dh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    if landscape:
        out = cv2.rotate(out, cv2.ROTATE_90_CLOCKWISE)
    return out


def _cut(card: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    h, w = card.shape[:2]
    x0, y0, x1, y1 = box
    return card[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)].copy()


def suppress_glare(img: np.ndarray) -> np.ndarray:
    """Inpaint blown-out specular highlights, then CLAHE on lightness."""
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    L = lab[:, :, 0]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    glare = ((L > 240) & (hsv[:, :, 1] < 40)).astype(np.uint8) * 255
    if glare.mean() > 0.5:  # anything worth inpainting
        glare = cv2.dilate(glare, np.ones((3, 3), np.uint8))
        img = cv2.inpaint(img, glare, 3, cv2.INPAINT_TELEA)
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(4, 4))
    lab[:, :, 0] = clahe.apply(lab[:, :, 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def zoom(img: np.ndarray, factor: float = 3.0) -> np.ndarray:
    big = cv2.resize(img, None, fx=factor, fy=factor, interpolation=cv2.INTER_CUBIC)
    blur = cv2.GaussianBlur(big, (0, 0), 1.2)
    return cv2.addWeighted(big, 1.6, blur, -0.6, 0)  # unsharp mask


def make_crops(image: np.ndarray, quad: np.ndarray) -> CardCrops:
    card = warp_card(image, quad)
    return crops_from_card(card)


def crops_from_card(card: np.ndarray) -> CardCrops:
    return CardCrops(
        card=card,
        art=_cut(card, ART_BOX),
        strip=zoom(suppress_glare(_cut(card, STRIP_BOX)), 3.0),
        set_symbol=zoom(suppress_glare(_cut(card, SET_SYMBOL_BOX)), 3.0),
        name_bar=zoom(suppress_glare(_cut(card, NAME_BAR_BOX)), 2.0),
    )


def texture_score(card: np.ndarray) -> float:
    """Rough 'is there a card here' measure — empty sleeves/pockets are flat."""
    g = cv2.cvtColor(card, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(g, cv2.CV_32F).var())
