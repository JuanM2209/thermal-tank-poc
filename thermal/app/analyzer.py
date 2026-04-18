"""
Tank level analyzer.

Principle:
  A full tank wall shows a clean temperature gradient where the liquid meets the
  gas/air headspace (different thermal capacity + radiative emissivity).
  For each ROI (a vertical strip on the tank wall), we:
    1. Compute the mean temperature per row -> 1D vertical profile.
    2. Smooth with a rolling mean.
    3. Compute |dT/dy| (vertical gradient magnitude).
    4. The interface row = argmax of gradient, provided it exceeds min_temp_delta.
    5. level_pct = (roi_bottom - interface_row) / roi_height * 100
"""

import numpy as np
import logging
from collections import deque

log = logging.getLogger("analyzer")


class TankAnalyzer:
    def __init__(self, tanks_config, smoothing=7, method="sobel",
                 invert_level=False, history=5):
        self.tanks = tanks_config
        self.smoothing = max(1, int(smoothing))
        self.method = method
        self.invert = invert_level
        # Per-tank rolling level history for simple median filtering
        self._hist = {t["id"]: deque(maxlen=history) for t in tanks_config}

    def _profile(self, strip):
        profile = strip.mean(axis=1)
        if self.smoothing > 1:
            k = np.ones(self.smoothing, dtype=np.float32) / self.smoothing
            profile = np.convolve(profile, k, mode="same")
        return profile

    def _gradient(self, profile):
        if self.method == "sobel":
            # 1-D Sobel (equivalent): convolve with [-1,0,1]/2
            kern = np.array([-1.0, 0.0, 1.0]) * 0.5
            g = np.convolve(profile, kern, mode="same")
            return np.abs(g)
        return np.abs(np.diff(profile, prepend=profile[0]))

    def analyze(self, thermal):
        results = []
        H, W = thermal.shape
        for t in self.tanks:
            r = t["roi"]
            x0, y0 = max(0, r["x"]), max(0, r["y"])
            x1 = min(W, x0 + r["w"])
            y1 = min(H, y0 + r["h"])
            strip = thermal[y0:y1, x0:x1]
            if strip.size == 0 or strip.shape[0] < 3:
                log.warning(f"ROI empty for {t['id']} (frame {W}x{H}, roi {r})")
                continue

            profile = self._profile(strip)
            grad = self._gradient(profile)
            peak_idx = int(np.argmax(grad))
            peak_val = float(grad[peak_idx])

            n = len(profile)
            # level_pct: 100% means liquid fills the ROI (interface at top of ROI)
            level_pct = (n - peak_idx) / n * 100.0
            if self.invert:
                level_pct = 100.0 - level_pct

            # Median smoothing across recent frames for stability
            hist = self._hist[t["id"]]
            hist.append(level_pct)
            level_stable = float(np.median(hist))

            min_delta = float(t.get("min_temp_delta", 1.0))
            confidence = "high" if peak_val >= min_delta else "low"

            results.append({
                "id": t["id"],
                "name": t["name"],
                "medium": t.get("medium", "unknown"),
                "level_pct": round(level_stable, 1),
                "level_pct_raw": round(level_pct, 1),
                "temp_min": round(float(strip.min()), 2),
                "temp_max": round(float(strip.max()), 2),
                "temp_avg": round(float(strip.mean()), 2),
                "gradient_peak": round(peak_val, 3),
                "interface_row": peak_idx,
                "confidence": confidence,
                "roi": r,
            })
        return results
