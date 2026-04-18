"""Unit tests for auto-calibration."""

from __future__ import annotations

import numpy as np
import pytest
from calibration import (
    EMISSIVITY_TABLE,
    MIN_THERMAL_DELTA_C,
    as_config_patch,
    calibrate,
)


def _gradient_frame(h: int = 192, w: int = 256) -> np.ndarray:
    """Scene with a vertical gradient — simulates liquid/gas split."""
    col = np.linspace(10.0, 50.0, h, dtype=np.float32)
    return np.broadcast_to(col.reshape(h, 1), (h, w)).astype(np.float32).copy()


def _flat_frame(h: int = 192, w: int = 256, temp: float = 25.0) -> np.ndarray:
    return np.full((h, w), temp, dtype=np.float32)


@pytest.mark.unit
class TestCalibrate:
    def test_no_frames_yields_default(self):
        result = calibrate([], rois=[])
        assert result.emissivity == EMISSIVITY_TABLE["unknown"]
        assert not result.range_locked
        assert "no frames captured" in result.notes

    def test_dominant_medium_chooses_emissivity(self):
        frames = [_gradient_frame() for _ in range(3)]
        rois = [{"x": 50, "y": 30, "w": 40, "h": 100}]
        result = calibrate(frames, rois, tank_mediums=["water", "water", "oil"])
        assert result.medium_dominant == "water"
        assert result.emissivity == EMISSIVITY_TABLE["water"]

    def test_oil_dominant(self):
        frames = [_gradient_frame() for _ in range(3)]
        rois = [{"x": 50, "y": 30, "w": 40, "h": 100}]
        result = calibrate(frames, rois, tank_mediums=["oil", "oil"])
        assert result.emissivity == EMISSIVITY_TABLE["oil"]

    def test_range_locked_when_delta_sufficient(self):
        frames = [_gradient_frame() for _ in range(5)]
        rois = [{"x": 50, "y": 30, "w": 40, "h": 100}]
        result = calibrate(frames, rois, tank_mediums=["water"])
        assert result.range_locked
        assert result.range_max_c > result.range_min_c
        assert result.thermal_delta_c >= MIN_THERMAL_DELTA_C

    def test_range_unlocked_when_scene_flat(self):
        frames = [_flat_frame(temp=25.0) for _ in range(5)]
        rois = [{"x": 50, "y": 30, "w": 40, "h": 100}]
        result = calibrate(frames, rois, tank_mediums=["water"])
        assert not result.range_locked
        assert any("delta" in note for note in result.notes)

    def test_reflect_temp_from_outside_pixels(self):
        # Outside is cold (10C), inside tank is very hot (50C) — reflect should lean cold.
        frame = _flat_frame(temp=10.0)
        roi = {"x": 100, "y": 50, "w": 40, "h": 80}
        frame[roi["y"]:roi["y"] + roi["h"], roi["x"]:roi["x"] + roi["w"]] = 50.0
        result = calibrate([frame, frame], rois=[roi], tank_mediums=["water"])
        assert result.reflect_temp_c == pytest.approx(10.0, abs=0.5)

    def test_output_rounded(self):
        frames = [_gradient_frame() for _ in range(3)]
        rois = [{"x": 50, "y": 30, "w": 40, "h": 100}]
        result = calibrate(frames, rois, tank_mediums=["water"])
        # Rounded to 2 dp — compare decimal representation
        assert len(str(result.range_min_c).split(".")[-1]) <= 2
        assert len(str(result.range_max_c).split(".")[-1]) <= 2


@pytest.mark.unit
class TestAsConfigPatch:
    def test_includes_ui_and_calibration(self):
        frames = [_gradient_frame() for _ in range(3)]
        rois = [{"x": 50, "y": 30, "w": 40, "h": 100}]
        result = calibrate(frames, rois, tank_mediums=["water"])
        patch = as_config_patch(result)
        assert "stream" in patch
        assert "ui" in patch
        assert "calibration" in patch
        assert patch["ui"]["emissivity"] == result.emissivity
        assert patch["calibration"]["calibrated_at"] == result.calibrated_at

    def test_stream_range_nulled_when_unlocked(self):
        frames = [_flat_frame() for _ in range(3)]
        rois = [{"x": 50, "y": 30, "w": 40, "h": 100}]
        result = calibrate(frames, rois, tank_mediums=["water"])
        patch = as_config_patch(result)
        assert patch["stream"]["range_min"] is None
        assert patch["stream"]["range_max"] is None

    def test_stream_range_set_when_locked(self):
        frames = [_gradient_frame() for _ in range(5)]
        rois = [{"x": 50, "y": 30, "w": 40, "h": 100}]
        result = calibrate(frames, rois, tank_mediums=["water"])
        patch = as_config_patch(result)
        assert patch["stream"]["range_min"] == result.range_min_c
        assert patch["stream"]["range_max"] == result.range_max_c
