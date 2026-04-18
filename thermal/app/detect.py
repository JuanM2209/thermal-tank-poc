"""Auto tank detection with classical OpenCV + medium classification.

No training data needed. Works well when tanks are vertical rectangles
thermally distinct from the background (warmer OR colder).

Pipeline
--------
1. (Optional) Median-reduce multiple frames to a single stable thermal frame.
2. Contrast-stretch the thermal frame.
3. Otsu + inverted Otsu masks (OR'd) to catch hot and cold tanks.
4. Vertical morphological close to fuse thin gaps.
5. findContours + boundingRect.
6. Keep rectangles that satisfy:
      aspect h/w in [1.5, 8]
      height >= 25 % of frame height
      width in [8 %, 55 %] of frame width
      no IoU overlap > 0.45 with a keeper
7. Rank by thermal contrast and interface-gradient score.
8. Classify each keeper as water | oil | unknown via `classifier.py`.
9. Number candidates left-to-right -> Tank 1, Tank 2, ...

Returns list[{id, name, medium, medium_confidence, roi, score, hint, features}].
"""

from __future__ import annotations

import cv2
import numpy as np

from classifier import MediumClassifier

_MIN_ASPECT = 1.5
_MAX_ASPECT = 8.0
_MIN_H_FRAC = 0.25
_MIN_W_FRAC = 0.08
_MAX_W_FRAC = 0.55
_IOU_LIMIT = 0.45


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
    H, W = thermal.shape
    inside = thermal[y:y + h, x:x + w]
    if inside.size == 0:
        return 0.0
    pad = 8
    ox0, oy0 = max(0, x - pad), max(0, y - pad)
    ox1, oy1 = min(W, x + w + pad), min(H, y + h + pad)
    outside = thermal[oy0:oy1, ox0:ox1].copy().astype(np.float32)
    outside[max(0, y - oy0):max(0, y - oy0) + h,
            max(0, x - ox0):max(0, x - ox0) + w] = np.nan
    omean = float(np.nanmean(outside))
    imean = float(np.mean(inside))
    span = float(thermal.max() - thermal.min()) or 1.0
    return abs(imean - omean) / span


def _stable_thermal(frames: list[np.ndarray] | None, fallback: np.ndarray) -> np.ndarray:
    if not frames:
        return fallback
    stack = np.stack([f.astype(np.float32) for f in frames], axis=0)
    return np.median(stack, axis=0)


def detect(
    thermal: np.ndarray,
    max_candidates: int = 4,
    frames: list[np.ndarray] | None = None,
) -> list[dict]:
    """Return up to `max_candidates` ROI boxes with medium classification."""
    if thermal is None or thermal.size == 0:
        return []

    stable = _stable_thermal(frames, thermal)
    H, W = stable.shape[:2]
    norm = cv2.normalize(stable, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)

    _, mask_hot = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, mask_cold = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    mask = cv2.bitwise_or(mask_hot, mask_cold)

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
        score = _contrast_score(stable, x, y, w, h)
        strip = stable[y:y + h, x:x + w]
        if strip.shape[0] >= 5:
            prof = strip.mean(axis=1)
            grad = np.abs(np.convolve(prof, [-1, 0, 1], mode="same"))
            score += 0.5 * float(grad.max()) / max(1e-3, stable.max() - stable.min())
        hint = "warm" if stable[y:y + h, x:x + w].mean() > stable.mean() else "cold"
        boxes.append((x, y, w, h, score, hint))

    boxes.sort(key=lambda b: b[4], reverse=True)
    keepers: list[tuple[int, int, int, int, float, str]] = []
    for b in boxes:
        rect = (b[0], b[1], b[2], b[3])
        if all(_iou(rect, (k[0], k[1], k[2], k[3])) < _IOU_LIMIT for k in keepers):
            keepers.append(b)
        if len(keepers) >= max_candidates:
            break

    # Left-to-right numbering so "Tank 1" is always the leftmost in frame.
    keepers.sort(key=lambda b: b[0])

    classifier = MediumClassifier()
    out: list[dict] = []
    for i, (x, y, w, h, s, hint) in enumerate(keepers, start=1):
        tank_id = f"tank_{i:02d}"
        roi = {"x": int(x), "y": int(y), "w": int(w), "h": int(h)}
        classification = classifier.classify(tank_id, stable, roi)
        medium = classification.medium
        if medium == "unknown":
            medium = "water" if hint == "cold" else "oil"
        out.append({
            "id": tank_id,
            "name": f"Tank {i}",
            "medium": medium,
            "medium_confidence": classification.confidence or (0.5 if hint else 0.0),
            "roi": roi,
            "score": round(float(s), 3),
            "hint": hint,
            "min_temp_delta": 0.8,
            "features": classification.features,
        })
    return out
