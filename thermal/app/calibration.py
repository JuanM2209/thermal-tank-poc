"""Auto-calibration of thermal display settings.

Given a recent window of (thermal, rois) samples the calibrator picks:

- `emissivity` based on the dominant medium across tanks
  (water 0.96, oil 0.94, steel 0.90, unknown 0.95)
- `reflect_temp_c` = mean of the coldest quartile of pixels OUTSIDE any ROI
- `range_min_c` / `range_max_c` = p1, p99 of pixels INSIDE any ROI with a
  +/- 2 C margin, clamped to sensor limits

Writes to `stream.range_min`, `stream.range_max`, `ui.emissivity` and
`ui.reflect_temp_c` through the normal config patch path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np

EMISSIVITY_TABLE: dict[str, float] = {
    "water": 0.96,
    "oil": 0.94,
    "steel": 0.90,
    "unknown": 0.95,
}
RANGE_MARGIN_C: float = 2.0
MIN_THERMAL_DELTA_C: float = 1.0
OUTSIDE_COLD_QUARTILE: float = 0.25


@dataclass(frozen=True)
class CalibrationResult:
    emissivity: float
    reflect_temp_c: float
    range_min_c: float
    range_max_c: float
    range_locked: bool
    calibrated_at: str
    notes: list[str]
    medium_dominant: str
    thermal_delta_c: float


def _build_outside_mask(shape: tuple[int, int], rois: list[dict]) -> np.ndarray:
    H, W = shape
    mask = np.ones((H, W), dtype=bool)
    for r in rois:
        x0 = max(0, int(r["x"]))
        y0 = max(0, int(r["y"]))
        x1 = min(W, x0 + int(r["w"]))
        y1 = min(H, y0 + int(r["h"]))
        if x1 > x0 and y1 > y0:
            mask[y0:y1, x0:x1] = False
    return mask


def _inside_pixels(thermal: np.ndarray, rois: list[dict]) -> np.ndarray:
    chunks: list[np.ndarray] = []
    H, W = thermal.shape[:2]
    for r in rois:
        x0 = max(0, int(r["x"]))
        y0 = max(0, int(r["y"]))
        x1 = min(W, x0 + int(r["w"]))
        y1 = min(H, y0 + int(r["h"]))
        if x1 > x0 and y1 > y0:
            chunks.append(thermal[y0:y1, x0:x1].ravel())
    if not chunks:
        return thermal.ravel()
    return np.concatenate(chunks)


def calibrate(
    frames: list[np.ndarray],
    rois: list[dict],
    tank_mediums: list[str] | None = None,
) -> CalibrationResult:
    """Compute calibration parameters from a list of thermal frames.

    `frames` should be the thermal (°C) frames captured over ~10 s.
    `rois` are the current tank ROIs (sensor coords).
    `tank_mediums` is the per-tank medium list (optional).
    """
    if not frames:
        return CalibrationResult(
            emissivity=EMISSIVITY_TABLE["unknown"],
            reflect_temp_c=20.0,
            range_min_c=0.0,
            range_max_c=50.0,
            range_locked=False,
            calibrated_at=_now_iso(),
            notes=["no frames captured"],
            medium_dominant="unknown",
            thermal_delta_c=0.0,
        )

    stack = np.stack([f.astype(np.float32) for f in frames], axis=0)
    avg_frame = stack.mean(axis=0)

    thermal_delta = float(avg_frame.max() - avg_frame.min())

    outside_mask = _build_outside_mask(avg_frame.shape, rois)
    outside_pixels = avg_frame[outside_mask]
    if outside_pixels.size == 0:
        reflect = float(np.mean(avg_frame))
    else:
        cutoff = float(np.quantile(outside_pixels, OUTSIDE_COLD_QUARTILE))
        coldest = outside_pixels[outside_pixels <= cutoff]
        reflect = float(np.mean(coldest)) if coldest.size else cutoff

    inside = _inside_pixels(avg_frame, rois)
    if inside.size:
        rmin = float(np.quantile(inside, 0.01)) - RANGE_MARGIN_C
        rmax = float(np.quantile(inside, 0.99)) + RANGE_MARGIN_C
    else:
        rmin = float(avg_frame.min())
        rmax = float(avg_frame.max())
    if rmax - rmin < MIN_THERMAL_DELTA_C:
        rmax = rmin + MIN_THERMAL_DELTA_C

    mediums = tank_mediums or []
    dominant = _dominant(mediums) if mediums else "unknown"
    emissivity = EMISSIVITY_TABLE.get(dominant, EMISSIVITY_TABLE["unknown"])

    notes: list[str] = []
    locked = True
    if thermal_delta < MIN_THERMAL_DELTA_C:
        locked = False
        notes.append(
            f"thermal delta {thermal_delta:.2f} C < {MIN_THERMAL_DELTA_C} C; "
            "readings will be flagged low-confidence until delta grows"
        )

    return CalibrationResult(
        emissivity=round(emissivity, 3),
        reflect_temp_c=round(reflect, 2),
        range_min_c=round(rmin, 2),
        range_max_c=round(rmax, 2),
        range_locked=locked,
        calibrated_at=_now_iso(),
        notes=notes,
        medium_dominant=dominant,
        thermal_delta_c=round(thermal_delta, 2),
    )


def _dominant(mediums: list[str]) -> str:
    counts: dict[str, int] = {}
    for m in mediums:
        counts[m] = counts.get(m, 0) + 1
    if not counts:
        return "unknown"
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def as_config_patch(result: CalibrationResult) -> dict:
    """Shape the calibration into a config patch the server can deep-merge."""
    return {
        "stream": {
            "range_min": result.range_min_c if result.range_locked else None,
            "range_max": result.range_max_c if result.range_locked else None,
        },
        "ui": {
            "emissivity": result.emissivity,
            "reflect_temp_c": result.reflect_temp_c,
        },
        "calibration": {
            "emissivity": result.emissivity,
            "reflect_temp_c": result.reflect_temp_c,
            "range_min_c": result.range_min_c,
            "range_max_c": result.range_max_c,
            "range_locked": result.range_locked,
            "calibrated_at": result.calibrated_at,
            "notes": result.notes,
            "medium_dominant": result.medium_dominant,
            "thermal_delta_c": result.thermal_delta_c,
        },
    }
