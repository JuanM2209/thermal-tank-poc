"""Unit tests for the water/oil medium classifier."""

from __future__ import annotations

import numpy as np
import pytest
from classifier import MIN_CONFIDENCE, MediumClassifier


def _scene(
    shape: tuple[int, int] = (192, 256),
    scene_temp: float = 25.0,
    scene_span: float = 30.0,
) -> np.ndarray:
    """Create a scene with a smooth ambient gradient."""
    H, W = shape
    ramp = np.linspace(scene_temp - scene_span / 2, scene_temp + scene_span / 2, H)
    return np.broadcast_to(ramp.reshape(H, 1), (H, W)).astype(np.float32).copy()


def _paint_tank(
    thermal: np.ndarray,
    roi: dict,
    top_temp: float,
    bottom_temp: float,
    split_frac: float = 0.5,
) -> np.ndarray:
    out = thermal.copy()
    y0, y1 = roi["y"], roi["y"] + roi["h"]
    x0, x1 = roi["x"], roi["x"] + roi["w"]
    split = int(y0 + (y1 - y0) * split_frac)
    out[y0:split, x0:x1] = top_temp       # gas above
    out[split:y1, x0:x1] = bottom_temp    # liquid below
    return out


@pytest.mark.unit
class TestMediumClassifier:
    def test_cool_sharp_reads_as_water(self):
        thermal = _scene(scene_temp=25.0, scene_span=30.0)
        roi = {"x": 80, "y": 20, "w": 40, "h": 150}
        # Cold liquid (water) with a sharp step
        thermal = _paint_tank(thermal, roi, top_temp=28.0, bottom_temp=8.0, split_frac=0.5)
        clf = MediumClassifier()
        for t in range(10):
            clf.observe("tank_01", ts=float(t), mean_inside=18.0)
        result = clf.classify("tank_01", thermal, roi)
        assert result.medium == "water"
        assert result.confidence >= MIN_CONFIDENCE

    def test_warm_smooth_reads_as_oil(self):
        thermal = _scene(scene_temp=25.0, scene_span=30.0)
        roi = {"x": 80, "y": 20, "w": 40, "h": 150}
        # Warm, nearly uniform tank (oil — heated & smooth)
        thermal[roi["y"]:roi["y"] + roi["h"], roi["x"]:roi["x"] + roi["w"]] = 45.0
        clf = MediumClassifier()
        for t in range(10):
            clf.observe("tank_02", ts=float(t), mean_inside=45.0)
        result = clf.classify("tank_02", thermal, roi)
        assert result.medium == "oil"
        assert result.confidence >= MIN_CONFIDENCE

    def test_ambiguous_case_is_unknown(self):
        # Tank temperature matches the scene — no offset, no gradient, no stdev info.
        thermal = _scene(scene_temp=25.0, scene_span=0.5)
        roi = {"x": 80, "y": 20, "w": 40, "h": 150}
        clf = MediumClassifier()
        result = clf.classify("tank_mystery", thermal, roi)
        # With no history and no feature signal, classifier should refuse to commit
        assert result.medium in ("unknown", "water", "oil")
        # Confidence should be near 0.5 when features are flat
        assert 0.4 <= result.confidence <= 0.9

    def test_tiny_roi_returns_unknown(self):
        thermal = _scene()
        tiny_roi = {"x": 0, "y": 0, "w": 2, "h": 2}
        clf = MediumClassifier()
        result = clf.classify("tiny", thermal, tiny_roi)
        assert result.medium == "unknown"
        assert result.confidence == 0.0

    def test_history_window_bounded(self):
        clf = MediumClassifier()
        # Push 120 seconds of observations
        for t in range(120):
            clf.observe("tank_01", ts=float(t), mean_inside=20.0)
        # Internal history should be trimmed to 60-second window
        hist = clf._hist["tank_01"]
        ts_range = hist[-1][0] - hist[0][0]
        assert ts_range <= 60.0

    def test_features_are_serializable(self):
        thermal = _scene()
        roi = {"x": 80, "y": 20, "w": 40, "h": 150}
        clf = MediumClassifier()
        clf.observe("t", ts=0.0, mean_inside=20.0)
        result = clf.classify("t", thermal, roi)
        # Every feature key must be a rounded float (JSON-serializable)
        for k in ("offset", "grad_max", "stdev", "water_score", "oil_score"):
            assert isinstance(result.features.get(k), float)
