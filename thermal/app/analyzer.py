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

v1.7 additions:
    interface_row_sensor (absolute Y px in sensor coords, for drawing the
    level line on the UI canvas), alarms_state (hi/lo crossings), layers
    (secondary gradient peaks when multi_layer is enabled per tank).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from typing import Any

import numpy as np

from classifier import Classification, MediumClassifier
from geometry import Geometry, compute as geometry_compute, parse_geometry, volume_ft3_at_level, ft3_to_bbl
from rate import RateEstimator

log = logging.getLogger("analyzer")

# Water-vs-oil classification is a statistical read across ~60 s of scene
# history — it has no meaningful frame-to-frame variation, so we only pay its
# cost once per second and cache the result per tank.
CLASSIFY_INTERVAL_S = 1.0

# Minimum row separation between two gradient peaks when multi_layer mode is
# on, expressed as a fraction of the ROI height. Prevents picking two rows
# that describe the same physical interface.
MULTI_LAYER_MIN_SEP_FRAC = 0.08
# Keep peaks at least this fraction of the top peak's magnitude. Rejects
# dishwater secondary peaks from imaging noise.
MULTI_LAYER_REL_FLOOR = 0.45


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
        self._classify_cache: dict[str, Classification] = {}
        self._classify_next_at: dict[str, float] = {}
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

    def _find_secondary_peak(
        self,
        grad: np.ndarray,
        primary_idx: int,
        min_sep: int,
        floor: float,
    ) -> int | None:
        """Find the second strongest local max in ``grad`` that is at least
        ``min_sep`` rows away from ``primary_idx`` and whose magnitude is
        above ``floor``.

        Returns the row index or None.
        """
        if grad.size < min_sep * 2 + 1:
            return None
        masked = grad.copy()
        lo = max(0, primary_idx - min_sep)
        hi = min(len(masked), primary_idx + min_sep + 1)
        masked[lo:hi] = 0.0
        idx = int(np.argmax(masked))
        if masked[idx] < floor:
            return None
        return idx

    def _alarms_state(self, t: dict, level_pct: float) -> dict[str, Any]:
        """Derive per-tank HI/LO alarm booleans from the tank config.

        Config shape (all optional):
            alarms:
              hi_pct: 90.0
              lo_pct: 10.0
        """
        alarms = t.get("alarms") or {}
        hi = alarms.get("hi_pct")
        lo = alarms.get("lo_pct")
        state: dict[str, Any] = {
            "hi_pct": float(hi) if hi is not None else None,
            "lo_pct": float(lo) if lo is not None else None,
            "hi": False,
            "lo": False,
        }
        if hi is not None and level_pct >= float(hi):
            state["hi"] = True
        if lo is not None and level_pct <= float(lo):
            state["lo"] = True
        return state

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

            # Absolute row inside the sensor frame — the UI needs this to
            # paint the level line on the canvas regardless of where the
            # ROI lives.
            interface_row_sensor = int(y0 + peak_idx)

            # Optional secondary interface (air/liquid is primary; a second
            # peak usually corresponds to a sludge or water-in-oil layer).
            layers: list[dict[str, Any]] | None = None
            if t.get("multi_layer"):
                min_sep = max(3, int(n * MULTI_LAYER_MIN_SEP_FRAC))
                floor = peak_val * MULTI_LAYER_REL_FLOOR
                sec_idx = self._find_secondary_peak(grad, peak_idx, min_sep, floor)
                layers = [
                    {
                        "label": "primary",
                        "row": peak_idx,
                        "row_sensor": interface_row_sensor,
                        "level_pct": round(level_pct, 1),
                        "gradient": round(peak_val, 3),
                    }
                ]
                if sec_idx is not None:
                    sec_level = (n - sec_idx) / n * 100.0
                    if self.invert:
                        sec_level = 100.0 - sec_level
                    # Label by relative position — whichever peak is lower
                    # in the tank is probably the sludge/water interface.
                    secondary_label = "sludge" if sec_idx > peak_idx else "upper"
                    layers.append(
                        {
                            "label": secondary_label,
                            "row": int(sec_idx),
                            "row_sensor": int(y0 + sec_idx),
                            "level_pct": round(sec_level, 1),
                            "gradient": round(float(grad[sec_idx]), 3),
                        }
                    )

            mean_inside = float(strip.mean())
            # Observe every frame (it's O(1) and feeds the temporal stdev),
            # but run the full classification at most once per second per tank.
            self._classifier.observe(t["id"], now, mean_inside)
            tid = t["id"]
            next_at = self._classify_next_at.get(tid, 0.0)
            cached = self._classify_cache.get(tid)
            if cached is None or now >= next_at:
                classification = self._classifier.classify(tid, thermal, r)
                self._classify_cache[tid] = classification
                self._classify_next_at[tid] = now + CLASSIFY_INTERVAL_S
            else:
                classification = cached
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

            alarms_state = self._alarms_state(t, level_stable)

            results.append(
                {
                    "id": t["id"],
                    "name": t["name"],
                    "topic": t.get("topic"),
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
                    "interface_row_sensor": interface_row_sensor,
                    "confidence": confidence,
                    "roi": r,
                    "geometry": _geometry_dict(geometry) if geometry else None,
                    "reading": reading_dict,
                    "alarms": alarms_state,
                    "layers": layers,
                }
            )
        return results

    def analyze_detailed(self, thermal: np.ndarray, tank_id: str) -> dict[str, Any] | None:
        """Expose the raw per-row profile + gradient for one tank.

        Used by the ``Why this reading?`` operator explainer so the UI can
        draw the thermal trace alongside the picked interface row. Re-runs
        the same math as :meth:`analyze` for a single ROI so callers do not
        have to pay for the full batch.
        """
        t = next((x for x in self.tanks if x.get("id") == tank_id), None)
        if t is None:
            return None
        H, W = thermal.shape
        r = t["roi"]
        x0, y0 = max(0, int(r["x"])), max(0, int(r["y"]))
        x1 = min(W, x0 + int(r["w"]))
        y1 = min(H, y0 + int(r["h"]))
        strip = thermal[y0:y1, x0:x1]
        if strip.size == 0 or strip.shape[0] < 3:
            return None
        profile = self._profile(strip)
        grad = self._gradient(profile)
        peak_idx = int(np.argmax(grad))
        return {
            "id": t["id"],
            "roi": r,
            "profile": [round(float(v), 3) for v in profile],
            "gradient": [round(float(v), 4) for v in grad],
            "peak_idx": peak_idx,
            "peak_val": round(float(grad[peak_idx]), 4),
            "min_temp_delta": float(t.get("min_temp_delta", 1.0)),
            "roi_height": int(strip.shape[0]),
            "y0": y0,
        }


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
