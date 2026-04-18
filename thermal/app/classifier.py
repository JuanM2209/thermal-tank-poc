"""Water vs oil classifier for thermal tank candidates.

Heuristics (pure functions, no training data required):

- Water: higher emissivity -> reads closer to true temperature, usually cooler
  than ambient, sharper liquid-gas gradient.
- Oil: lower emissivity -> reads colder than reality, tanks are often heated
  or insulated so interior is warmer than ambient, gradient is softer.

Features
--------
1. thermal offset   = (mean_inside - scene_median) / scene_span
2. temporal std     = std of inside-mean across a 60 s history
3. gradient sharpness = max |dT/dy| inside the ROI, normalised by scene span

Score (logistic-style blend, tuned to the PoC data we have; easy to refit):

    water_score = w_cool * clamp(-offset) + w_sharp * gradient + w_stable * (1/std)
    oil_score   = w_warm * clamp(+offset) + w_smooth * (1 - gradient)

Returns (medium, confidence) where confidence = softmax(water_score, oil_score).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from typing import Literal

import numpy as np

Medium = Literal["water", "oil", "unknown"]

W_COOL: float = 1.4
W_SHARP: float = 1.0
W_STABLE: float = 0.6
W_WARM: float = 1.4
W_SMOOTH: float = 0.5
MIN_CONFIDENCE: float = 0.60
HISTORY_SECONDS: float = 60.0


@dataclass(frozen=True)
class Classification:
    medium: Medium
    confidence: float           # 0..1
    features: dict[str, float]


def _clamp_pos(x: float) -> float:
    return x if x > 0 else 0.0


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


class MediumClassifier:
    """Stateful classifier — keeps a small history per tank to compute std."""

    def __init__(self):
        # tank_id -> deque of (ts, mean_inside)
        self._hist: dict[str, deque[tuple[float, float]]] = {}

    def observe(self, tank_id: str, ts: float, mean_inside: float) -> None:
        h = self._hist.setdefault(tank_id, deque())
        h.append((ts, mean_inside))
        cutoff = ts - HISTORY_SECONDS
        while h and h[0][0] < cutoff:
            h.popleft()

    def classify(
        self,
        tank_id: str,
        thermal: np.ndarray,
        roi: dict,
    ) -> Classification:
        H, W = thermal.shape[:2]
        x0 = max(0, int(roi["x"]))
        y0 = max(0, int(roi["y"]))
        x1 = min(W, x0 + int(roi["w"]))
        y1 = min(H, y0 + int(roi["h"]))
        inside = thermal[y0:y1, x0:x1]
        if inside.size < 9:
            return Classification("unknown", 0.0, {})

        scene_median = float(np.median(thermal))
        scene_span = float(thermal.max() - thermal.min()) or 1.0
        mean_inside = float(inside.mean())
        offset = (mean_inside - scene_median) / scene_span

        # Vertical gradient sharpness inside the ROI
        if inside.shape[0] >= 3:
            profile = inside.mean(axis=1)
            grad = np.abs(np.diff(profile, prepend=profile[0]))
            grad_max = float(grad.max()) / scene_span
        else:
            grad_max = 0.0

        # Temporal stability (std of mean_inside over the last ~60 s)
        h = self._hist.get(tank_id)
        if h and len(h) >= 4:
            stdev = float(np.std([v for _, v in h]))
        else:
            stdev = 0.0
        stability = 1.0 / (1.0 + stdev)   # in (0, 1]

        water_score = (
            W_COOL * _clamp_pos(-offset)
            + W_SHARP * grad_max
            + W_STABLE * stability
        )
        oil_score = (
            W_WARM * _clamp_pos(offset)
            + W_SMOOTH * (1.0 - min(grad_max, 1.0))
        )

        diff = water_score - oil_score
        p_water = _sigmoid(2.0 * diff)
        confidence = max(p_water, 1.0 - p_water)
        medium: Medium
        if confidence < MIN_CONFIDENCE:
            medium = "unknown"
        else:
            medium = "water" if p_water >= 0.5 else "oil"

        return Classification(
            medium=medium,
            confidence=round(confidence, 2),
            features={
                "offset": round(offset, 3),
                "grad_max": round(grad_max, 3),
                "stdev": round(stdev, 3),
                "water_score": round(water_score, 3),
                "oil_score": round(oil_score, 3),
            },
        )
