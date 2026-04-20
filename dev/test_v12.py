"""Synthetic smoke test for the v1.12 row-majority + EMA + monotonicity
algorithm. Run from Z:\\thermal-tank-poc:

    python -m pytest dev/test_v12.py -q
or
    python dev/test_v12.py
"""

from __future__ import annotations

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "thermal", "app"))

import analyzer as A  # noqa: E402


def _strip_half_full(h=30, w=16, cold=10.0, warm=25.0):
    s = np.full((h, w), warm, dtype=np.float32)
    s[h // 2 :] = cold
    return s


def _strip_bottle_middle(h=30, w=16, cold=10.0, warm=25.0):
    # Small bottle occupying 5/16 columns (31 %) — no row is majority-warm,
    # so the row-majority detector correctly reports 0 % and skips the
    # monotonicity gate (trivially monotonic "entirely gas" scene).
    s = np.full((h, w), cold, dtype=np.float32)
    s[10:15, 5:10] = warm
    return s


def _strip_wide_object_middle(h=30, w=16, cold=10.0, warm=25.0):
    # Hand-shaped warm patch spanning the full ROI width at rows 10–17.
    # With warm=liquid polarity this creates a row-majority interface
    # in the MIDDLE of the ROI, but there is no liquid below it, so the
    # monotonicity score must be negative and the gate must refuse.
    s = np.full((h, w), cold, dtype=np.float32)
    s[10:18, :] = warm
    return s


def _strip_uniform(h=30, w=16, t=15.0):
    # A wall / torso in the ROI — temperature is uniform to within sensor
    # noise. Real sensors have ~0.05 °C NETD, so 0.02 °C noise is realistic.
    return np.full((h, w), t, dtype=np.float32) + np.random.RandomState(0).randn(h, w) * 0.02


def main():
    print("=" * 70)
    print("v1.12 analyzer synthetic smoke test")
    print("=" * 70)

    # Test 1: 50% liquid (cold at bottom)
    s = _strip_half_full()
    r = A._otsu_level(s, liquid_is_cold=True)
    print("Half-full:  level_pct={:.1f}  level_row={}  eta={:.2f}  mono={:.2f}".format(
        r["level_pct"], r["level_row"], r["eta"], r["monotonicity"]
    ))
    assert 40 <= r["level_pct"] <= 60, "expected ~50% for half-full strip"
    assert r["monotonicity"] >= A.MONOTONICITY_MIN, "monotonicity should pass for real interface"

    # Test 2a: tiny 5%-area bottle in the middle.
    # Row-majority detector correctly reports 0 % (no majority row)
    # so it never triggers a false interface — this is the v0.8.0
    # bug case ("5 % area → 35 % reading") now reading correctly.
    s = _strip_bottle_middle()
    r_forced = A._otsu_level(s, liquid_is_cold=False)
    print("Tiny-bottle (warm=liquid forced): level_pct={:.1f} level_row={}".format(
        r_forced["level_pct"], r_forced["level_row"]
    ))
    assert r_forced["level_pct"] == 0.0, "tiny bottle must not raise level above 0"

    # Test 2b: WIDE object (e.g. a hand) spanning the full ROI width at
    # rows 10-17. With warm=liquid the row-majority detector picks row
    # 10 as interface, but there is no liquid below row 18 → monotonicity
    # gate MUST fail so the system refuses the bogus reading.
    s = _strip_wide_object_middle()
    r_hand = A._otsu_level(s, liquid_is_cold=False)
    print("Hand-full-width (warm=liquid forced): level_pct={:.1f} level_row={} mono={:.2f}".format(
        r_hand["level_pct"], r_hand["level_row"], r_hand["monotonicity"]
    ))
    assert r_hand["level_row"] < 20, "row-majority should find interface at hand top"
    assert r_hand["monotonicity"] < A.MONOTONICITY_MIN, \
        "mid-ROI object with no liquid below MUST fail monotonicity"

    # Test 3: uniform ROI.
    # η alone is a scale-invariant ratio (high even for pure Gaussian noise)
    # so we verify the actual production gate — the span + std + η combo
    # that analyze() applies — refuses the reading.
    s = _strip_uniform()
    span = float(s.max() - s.min())
    std = float(s.std())
    r = A._otsu_level(s, liquid_is_cold=None)
    print("Uniform:    span={:.2f}  std={:.3f}  eta={:.3f}".format(span, std, r["eta"]))
    gated = (
        span < A.OTSU_CONTRAST_MIN_C
        or std < A.OTSU_STDDEV_MIN_C
        or r["eta"] < A.OTSU_ETA_MIN
    )
    assert gated, "uniform ROI must fail at least one of the three gates"

    # Test 4: EMA smoothing
    s = _strip_half_full()
    r1 = A._otsu_level(s, liquid_is_cold=True, prev_threshold=10.0)
    print("EMA blend:  raw={:.2f}  smoothed={:.2f}  (alpha={})".format(
        r1["threshold_c_raw"], r1["threshold_c"], A.OTSU_EMA_ALPHA
    ))
    expected = A.OTSU_EMA_ALPHA * r1["threshold_c_raw"] + (1 - A.OTSU_EMA_ALPHA) * 10.0
    assert abs(r1["threshold_c"] - expected) < 0.01, "EMA math check"

    # Test 5: full pipeline — TankAnalyzer.analyze() composes all gates
    # and we want the "wide hand in ROI" case to come back with
    # reliability="uniform" and low_monotonicity in reasons.
    tank_cfg = [{
        "id": "T01", "name": "Test", "topic": "t",
        "roi": {"x": 0, "y": 0, "w": 16, "h": 30},
        "min_temp_delta": 1.0,
        "liquid_is_cold": False,  # force warm=liquid to reproduce the bug
    }]
    ta = A.TankAnalyzer(tank_cfg)
    # Hand-full-width scene wrapped as a full "sensor frame" (same shape)
    s = _strip_wide_object_middle()
    res = ta.analyze(s)
    assert len(res) == 1
    r = res[0]
    print("Pipeline:   reliability={} level_pct={} reasons={}".format(
        r["reliability"], r["level_pct"], r["reliability_reasons"]
    ))
    assert r["reliability"] == "uniform", "hand-in-ROI must trigger uniform"
    assert "low_monotonicity" in r["reliability_reasons"], \
        "low_monotonicity must appear in reasons"
    assert r["level_pct"] is None, "no level should be reported when gate fails"

    # Test 6: EMA convergence — feed the same scene twice, confirm the
    # smoothed threshold moves toward the raw threshold over frames.
    ta2 = A.TankAnalyzer([{
        "id": "T02", "name": "T2",
        "roi": {"x": 0, "y": 0, "w": 16, "h": 30},
        "min_temp_delta": 1.0,
    }])
    s = _strip_half_full()
    r1 = ta2.analyze(s)[0]
    r2 = ta2.analyze(s)[0]
    r3 = ta2.analyze(s)[0]
    print("EMA pipeline: t1_raw={} t1={} t2={} t3={}".format(
        r1["otsu_threshold_c_raw"], r1["otsu_threshold_c"],
        r2["otsu_threshold_c"], r3["otsu_threshold_c"],
    ))
    # Raw should be constant across frames since scene is static; smoothed
    # should converge to it.
    assert abs(r3["otsu_threshold_c"] - r3["otsu_threshold_c_raw"]) \
        <= abs(r1["otsu_threshold_c"] - r1["otsu_threshold_c_raw"]), \
        "EMA should converge toward raw over successive frames"

    print()
    print("All assertions passed.")


if __name__ == "__main__":
    main()
