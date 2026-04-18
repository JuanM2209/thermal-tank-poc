"""Thermal palette rendering + overlay drawing.

Keeps all visual concerns out of the capture / analysis pipeline.
"""

from __future__ import annotations

import cv2
import numpy as np

# Built-in OpenCV colormaps we expose
_CV_MAPS = {
    "rainbow":  cv2.COLORMAP_RAINBOW,
    "hot":      cv2.COLORMAP_HOT,
    "inferno":  cv2.COLORMAP_INFERNO,
    "plasma":   cv2.COLORMAP_PLASMA,
    "magma":    cv2.COLORMAP_MAGMA,
    "jet":      cv2.COLORMAP_JET,
    "turbo":    cv2.COLORMAP_TURBO,
    "cividis":  cv2.COLORMAP_CIVIDIS,
}


def _iron_lut() -> np.ndarray:
    """Classic FLIR 'iron' palette (black -> purple -> red -> yellow -> white)."""
    stops = [
        (0.00, (0,   0,   0)),
        (0.20, (40,  0,   80)),
        (0.35, (120, 0,   130)),
        (0.50, (200, 30,  70)),
        (0.65, (230, 95,  0)),
        (0.80, (255, 180, 0)),
        (0.92, (255, 230, 120)),
        (1.00, (255, 255, 255)),
    ]
    lut = np.zeros((256, 1, 3), dtype=np.uint8)
    for i in range(256):
        t = i / 255.0
        for k in range(len(stops) - 1):
            t0, c0 = stops[k]
            t1, c1 = stops[k + 1]
            if t0 <= t <= t1:
                f = 0 if t1 == t0 else (t - t0) / (t1 - t0)
                r = int(c0[0] + (c1[0] - c0[0]) * f)
                g = int(c0[1] + (c1[1] - c0[1]) * f)
                b = int(c0[2] + (c1[2] - c0[2]) * f)
                lut[i, 0] = (b, g, r)  # OpenCV BGR
                break
    return lut


_IRON_LUT = _iron_lut()
PALETTES = ("grayscale", "iron", "rainbow", "hot", "inferno", "plasma",
            "magma", "jet", "turbo", "cividis")


def normalize_thermal(thermal_c: np.ndarray) -> tuple[np.ndarray, float, float]:
    """Contrast-stretch the thermal frame to 0..255 and return min/max used."""
    tmin = float(thermal_c.min())
    tmax = float(thermal_c.max())
    span = max(1e-3, tmax - tmin)
    norm = np.clip((thermal_c - tmin) / span * 255.0, 0, 255).astype(np.uint8)
    return norm, tmin, tmax


def render(thermal_c: np.ndarray, palette: str = "iron") -> tuple[np.ndarray, float, float]:
    """Return a BGR visualisation of the thermal frame + the (min, max) °C used."""
    norm, tmin, tmax = normalize_thermal(thermal_c)
    p = (palette or "iron").lower()
    if p == "grayscale":
        bgr = cv2.cvtColor(norm, cv2.COLOR_GRAY2BGR)
    elif p == "iron":
        bgr = cv2.LUT(cv2.cvtColor(norm, cv2.COLOR_GRAY2BGR), _IRON_LUT)
    elif p in _CV_MAPS:
        bgr = cv2.applyColorMap(norm, _CV_MAPS[p])
    else:
        # Unknown name -> fall back to iron rather than crash
        bgr = cv2.LUT(cv2.cvtColor(norm, cv2.COLOR_GRAY2BGR), _IRON_LUT)
    return bgr, tmin, tmax


def blend_with_visual(visual_bgr: np.ndarray, palette_bgr: np.ndarray,
                      alpha: float = 0.55) -> np.ndarray:
    """Blend the colour-mapped thermal on top of the visible-light frame."""
    if visual_bgr.shape[:2] != palette_bgr.shape[:2]:
        palette_bgr = cv2.resize(palette_bgr, (visual_bgr.shape[1], visual_bgr.shape[0]))
    return cv2.addWeighted(palette_bgr, alpha, visual_bgr, 1.0 - alpha, 0)


def find_hot_cold(thermal_c: np.ndarray) -> tuple[tuple[int, int, float], tuple[int, int, float]]:
    """Locate the hottest and coldest pixel — returns ((x, y, °C), (x, y, °C))."""
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(thermal_c)
    hot = (int(max_loc[0]), int(max_loc[1]), float(max_val))
    cold = (int(min_loc[0]), int(min_loc[1]), float(min_val))
    return hot, cold
