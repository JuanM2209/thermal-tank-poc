"""Unit tests for the rate estimator."""

from __future__ import annotations

import pytest
from rate import (
    DEFAULT_STABLE_SIGN_SECONDS,
    RateEstimator,
    _hampel_keep,
    _linear_slope,
    _median,
)


@pytest.mark.unit
class TestMedian:
    def test_odd_count(self):
        assert _median([3.0, 1.0, 2.0]) == 2.0

    def test_even_count(self):
        assert _median([1.0, 2.0, 3.0, 4.0]) == 2.5

    def test_single(self):
        assert _median([5.0]) == 5.0


@pytest.mark.unit
class TestHampel:
    def test_pass_through_small(self):
        assert _hampel_keep([1.0, 2.0, 3.0]) == [True, True, True]

    def test_drops_outlier(self):
        values = [10.0, 10.1, 10.05, 10.08, 10.02, 50.0]
        keep = _hampel_keep(values)
        assert keep[-1] is False
        assert all(keep[:-1])

    def test_all_equal_keeps_everything(self):
        # MAD == 0 short-circuits to keep all
        assert _hampel_keep([5.0] * 6) == [True] * 6


@pytest.mark.unit
class TestLinearSlope:
    def test_increasing_series(self):
        ts = [0.0, 1.0, 2.0, 3.0]
        vs = [0.0, 1.0, 2.0, 3.0]
        assert pytest.approx(_linear_slope(ts, vs), abs=1e-9) == 1.0

    def test_flat_series(self):
        assert _linear_slope([0.0, 1.0, 2.0], [5.0, 5.0, 5.0]) == 0.0

    def test_single_point_returns_zero(self):
        assert _linear_slope([0.0], [1.0]) == 0.0


@pytest.mark.unit
class TestRateEstimator:
    def test_insufficient_samples(self):
        r = RateEstimator()
        r.push(10.0, now=0.0)
        r.push(11.0, now=1.0)
        snap = r.snapshot(100.0, 11.0, now=2.0)
        assert snap.fill_rate_bbl_h == 0.0
        assert snap.minutes_to_full is None
        assert snap.minutes_to_empty is None

    def test_fill_rate_positive(self):
        r = RateEstimator(stable_sign_seconds=0.0)
        for i in range(10):
            r.push(i * 1.0, now=float(i))        # +1 bbl per sec
        snap = r.snapshot(100.0, 9.0, now=9.0)
        assert snap.fill_rate_bbl_h == pytest.approx(3600.0, rel=0.05)
        assert snap.minutes_to_full is not None
        assert snap.minutes_to_empty is None

    def test_drain_rate_negative(self):
        r = RateEstimator(stable_sign_seconds=0.0)
        for i in range(10):
            r.push(100.0 - i * 1.0, now=float(i))
        snap = r.snapshot(100.0, 91.0, now=9.0)
        assert snap.fill_rate_bbl_h < 0
        assert snap.minutes_to_empty is not None
        assert snap.minutes_to_full is None

    def test_sign_stability_gate(self):
        r = RateEstimator(stable_sign_seconds=60.0)
        for i in range(10):
            r.push(i * 1.0, now=float(i))
        snap = r.snapshot(100.0, 9.0, now=9.0)
        assert snap.fill_rate_bbl_h > 0
        # Not enough elapsed sign-stable time → no ETA yet
        assert snap.minutes_to_full is None

    def test_window_trimming(self):
        r = RateEstimator(window_seconds=10.0, stable_sign_seconds=0.0)
        r.push(0.0, now=0.0)
        r.push(5.0, now=5.0)
        r.push(100.0, now=200.0)   # Much later → older samples dropped
        snap = r.snapshot(200.0, 100.0, now=200.0)
        # Only one sample inside the window → not enough for a slope
        assert snap.samples_used <= 1
        assert snap.fill_rate_bbl_h == 0.0

    def test_outlier_rejected_by_hampel(self):
        r = RateEstimator(stable_sign_seconds=0.0)
        base = [(float(i), i * 0.5) for i in range(8)]
        base.append((8.0, 999.0))  # spike
        for ts, v in base:
            r.push(v, now=ts)
        snap = r.snapshot(1000.0, 3.5, now=8.0)
        # Slope should stay close to +0.5 bbl/s == 1800 bbl/h
        assert snap.fill_rate_bbl_h == pytest.approx(1800.0, rel=0.15)
        assert snap.samples_used == 8

    def test_eta_to_full_uses_remaining(self):
        r = RateEstimator(stable_sign_seconds=0.0)
        # 60 bbl/h fill, 30 bbl to full => 30 minutes
        for i in range(10):
            r.push(i * (60.0 / 3600.0), now=float(i))
        snap = r.snapshot(
            geometry_volume_full_bbl=30.0 + 9 * (60.0 / 3600.0),
            current_volume_bbl=9 * (60.0 / 3600.0),
            now=9.0,
        )
        assert snap.fill_rate_bbl_h == pytest.approx(60.0, rel=0.05)
        assert snap.minutes_to_full == pytest.approx(30.0, abs=2.0)

    def test_reset_clears_state(self):
        r = RateEstimator()
        for i in range(5):
            r.push(i * 1.0, now=float(i))
        r.reset()
        snap = r.snapshot(100.0, 5.0, now=5.0)
        assert snap.samples_used == 0
        assert snap.fill_rate_bbl_h == 0.0


@pytest.mark.unit
def test_default_stable_sign_seconds_is_two_minutes():
    assert DEFAULT_STABLE_SIGN_SECONDS == 120.0
