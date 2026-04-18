"""Tank level analyzer.

Principle:
  A full tank wall shows a clean temperature gradient where the liquid meets
  the gas/air headspace (different thermal capacity + radiative emissivity).
  For each ROI (vertical strip on a tank wall), we:
    1. Mean-per-row -> 1D vertical temperature profile
    2. Smooth with a rolling mean
    3. |dT/dy| gradient magnitude
    4. interface row = argmax of gradient (if it exceeds min_temp_delta)
    5. level_pct = (roi_bottom - interface_row) / roi_height * 100

Output per tank (new in v1):
    level_pct, level_raw_pct, temp_min/max/avg, gradient_peak, confidence,
    medium, medium_confidence, geometry (dict), reading (dict), calibration
    (placeholder — filled in by Pipeline wrapping the analyzer).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

import numpy as np

from classifier import MediumClassifier
from geometry import Geometry, compute as geometry_compute, parse_geometry, volume_ft3_at_level, ft3_to_bbl
from rate import RateEstimator

log = logging.getLogger("analyzer")


class TankAnalyzer:
    def __init__(
        self,
        tanks_config: list[dict],
        smoothing: int = 7,
        method: str = "sobel",
        invert_level: bool = False,
        history: int = 5,
    ):
        self.tanks = tanks_config
        self.smoothing = max(1, int(smoothing))
        self.method = method
        self.invert = invert_level
        self._level_hist: dict[str, deque[float]] = {
            t["id"]: deque(maxlen=history) for t in tanks_config
        }
        self._classifier = MediumClassifier()
        self._rate: dict[str, RateEstimator] = {
            t["id"]: RateEstimator() for t in tanks_config
        }

    # ----- internal helpers ------------------------------------------------
    def _profile(self, strip: np.ndarray) -> np.ndarray:
        profile = strip.mean(axis=1)
        if self.smoothing > 1:
            k = np.ones(self.smoothing, dtype=np.float32) / self.smoothing
            profile = np.convolve(profile, k, mode="same")
        return profile

    def _gradient(self, profile: np.ndarray) -> np.ndarray:
        if self.method == "sobel":
            kern = np.array([-1.0, 0.0, 1.0]) * 0.5
            g = np.convolve(profile, kern, mode="same")
            return np.abs(g)
        return np.abs(np.diff(profile, prepend=profile[0]))

    # ----- public API ------------------------------------------------------
    def analyze(self, thermal: np.ndarray) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        H, W = thermal.shape
        now = time.time()

        for t in self.tanks:
            r = t["roi"]
            x0, y0 = max(0, int(r["x"])), max(0, int(r["y"]))
            x1 = min(W, x0 + int(r["w"]))
            y1 = min(H, y0 + int(r["h"]))
            strip = thermal[y0:y1, x0:x1]
            if strip.size == 0 or strip.shape[0] < 3:
                log.warning(f"ROI empty for {t['id']} (frame {W}x{H}, roi {r})")
                continue

            profile = self._profile(strip)
            grad = self._gradient(profile)
            peak_idx = int(np.argmax(grad))
            peak_val = float(grad[peak_idx])

            n = len(profile)
            level_pct = (n - peak_idx) / n * 100.0
            if self.invert:
                level_pct = 100.0 - level_pct

            hist = self._level_hist.setdefault(t["id"], deque(maxlen=5))
            hist.append(level_pct)
            level_stable = float(np.median(hist))

            min_delta = float(t.get("min_temp_delta", 1.0))
            confidence = "high" if peak_val >= min_delta else "low"

            mean_inside = float(strip.mean())
            self._classifier.observe(t["id"], now, mean_inside)
            classification = self._classifier.classify(t["id"], thermal, r)
            declared_medium = t.get("medium")
            medium = declared_medium or classification.medium

            geometry = parse_geometry(t.get("geometry"))
            reading_dict: dict[str, Any] | None = None
            rate_snapshot = None
            if geometry is not None:
                reading = geometry_compute(geometry, level_stable)
                est = self._rate.setdefault(t["id"], RateEstimator())
                est.push(reading.volume_bbl, now=now)
                full_ft3 = volume_ft3_at_level(geometry, geometry.height_ft)
                full_bbl = ft3_to_bbl(full_ft3)
                rate_snapshot = est.snapshot(
                    geometry_volume_full_bbl=full_bbl,
                    current_volume_bbl=reading.volume_bbl,
                    now=now,
                )
                reading_dict = {
                    "level_ft": reading.level_ft,
                    "level_in": reading.level_in,
                    "volume_bbl": reading.volume_bbl,
                    "volume_gal": reading.volume_gal,
                    "ullage_ft": reading.ullage_ft,
                    "volume_full_bbl": round(full_bbl, 1),
                    "fill_rate_bbl_h": rate_snapshot.fill_rate_bbl_h,
                    "minutes_to_full": rate_snapshot.minutes_to_full,
                    "minutes_to_empty": rate_snapshot.minutes_to_empty,
                }

            results.append(
                {
                    "id": t["id"],
                    "name": t["name"],
                    "medium": medium,
                    "medium_declared": declared_medium or None,
                    "medium_confidence": classification.confidence,
                    "medium_features": classification.features,
                    "level_pct": round(level_stable, 1),
                    "level_pct_raw": round(level_pct, 1),
                    "temp_min": round(float(strip.min()), 2),
                    "temp_max": round(float(strip.max()), 2),
                    "temp_avg": round(mean_inside, 2),
                    "gradient_peak": round(peak_val, 3),
                    "interface_row": peak_idx,
                    "confidence": confidence,
                    "roi": r,
                    "geometry": _geometry_dict(geometry) if geometry else None,
                    "reading": reading_dict,
                }
            )
        return results


def _geometry_dict(g: Geometry) -> dict[str, Any]:
    d: dict[str, Any] = {
        "height_ft": g.height_ft,
        "diameter_ft": g.diameter_ft,
        "shape": g.shape,
    }
    if g.shape == "rectangular":
        d["length_ft"] = g.length_ft
        d["width_ft"] = g.width_ft
    return d
