"""Auto tank detection with classical OpenCV.

No training data needed. Works well when tanks are vertical rectangles
thermally distinct from the background (warmer OR colder).

Pipeline:
  1. Contrast-stretch the thermal frame.
  2. Otsu threshold + inverted Otsu threshold (cover both warm & cold tanks).
  3. Morphological close to fill gaps (vertical kernel — tanks are tall).
  4. findContours + boundingRect.
  5. Keep rectangles that:
       - aspect ratio h/w in [1.5, 8]
       - min height  >= 25% of frame height
       - min width   >= 8% of frame width
       - no overlap > 0.5 IoU with a keeper
  6. Rank by thermal contrast inside the box vs. outside.
  7. Return up to N candidates.

Returns shape: list of {id, roi:{x,y,w,h}, score, hint}.
"""

from __future__ import annotations

import cv2
import numpy as np

_MIN_ASPECT = 1.5    # h/w
_MAX_ASPECT = 8.0
_MIN_H_FRAC = 0.25   # relative to frame height
_MIN_W_FRAC = 0.08   # relative to frame width
_MAX_W_FRAC = 0.55   # rule out "whole frame is bright"
_IOU_LIMIT  = 0.45


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    inter_x1 = max(ax, bx)
    inter_y1 = max(ay, by)
    inter_x2 = min(ax + aw, bx + bw)
    inter_y2 = min(ay + ah, by + bh)
    iw = max(0, inter_x2 - inter_x1)
    ih = max(0, inter_y2 - inter_y1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter
    return inter / union if union else 0.0


def _contrast_score(thermal: np.ndarray, x: int, y: int, w: int, h: int) -> float:
    """Mean |temp inside ROI - temp outside ROI|, normalised."""
    H, W = thermal.shape
    inside = thermal[y:y + h, x:x + w]
    if inside.size == 0:
        return 0.0
    # Outside = an expanded box minus the ROI
    pad = 8
    ox0, oy0 = max(0, x - pad), max(0, y - pad)
    ox1, oy1 = min(W, x + w + pad), min(H, y + h + pad)
    outside = thermal[oy0:oy1, ox0:ox1].copy()
    outside[max(0, y - oy0):max(0, y - oy0) + h,
            max(0, x - ox0):max(0, x - ox0) + w] = np.nan
    omean = np.nanmean(outside)
    imean = float(np.mean(inside))
    span = float(thermal.max() - thermal.min()) or 1.0
    return abs(imean - omean) / span


def detect(thermal: np.ndarray, max_candidates: int = 4) -> list[dict]:
    """Return up to `max_candidates` ROI boxes (sensor coords)."""
    if thermal is None or thermal.size == 0:
        return []
    H, W = thermal.shape[:2]
    norm = cv2.normalize(thermal, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    # Otsu + inverted Otsu — combined via OR to catch both hot and cold tanks
    _, mask_hot = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, mask_cold = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    mask = cv2.bitwise_or(mask_hot, mask_cold)

    # Vertical-biased close to fuse thin gaps between scanlines
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 9))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes: list[tuple[int, int, int, int, float, str]] = []
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w < 2 or h < 2:
            continue
        ar = h / max(1, w)
        if ar < _MIN_ASPECT or ar > _MAX_ASPECT:
            continue
        if h < _MIN_H_FRAC * H or w < _MIN_W_FRAC * W or w > _MAX_W_FRAC * W:
            continue
        # Per-box thermal contrast + mean gradient magnitude (how "wall-like")
        score = _contrast_score(thermal, x, y, w, h)
        # boost score if there is a strong |dT/dy| inside (interface candidate)
        strip = thermal[y:y + h, x:x + w]
        if strip.shape[0] >= 5:
            prof = strip.mean(axis=1)
            grad = np.abs(np.convolve(prof, [-1, 0, 1], mode="same"))
            score += 0.5 * float(grad.max()) / max(1e-3, thermal.max() - thermal.min())
        # Label which pool (warm vs cold)
        hint = "warm" if thermal[y:y + h, x:x + w].mean() > thermal.mean() else "cold"
        boxes.append((x, y, w, h, score, hint))

    # Sort by score descending, apply NMS by IoU
    boxes.sort(key=lambda b: b[4], reverse=True)
    keepers: list[tuple[int, int, int, int, float, str]] = []
    for b in boxes:
        rect = (b[0], b[1], b[2], b[3])
        if all(_iou(rect, (k[0], k[1], k[2], k[3])) < _IOU_LIMIT for k in keepers):
            keepers.append(b)
        if len(keepers) >= max_candidates:
            break

    out = []
    for i, (x, y, w, h, s, hint) in enumerate(keepers, start=1):
        out.append({
            "id": f"auto_{i:02d}",
            "name": f"Auto {i}",
            "medium": "water" if hint == "cold" else "oil",
            "roi": {"x": int(x), "y": int(y), "w": int(w), "h": int(h)},
            "score": round(float(s), 3),
            "hint": hint,
            "min_temp_delta": 0.8,
        })
    return out
