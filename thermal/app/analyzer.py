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

v1.8 reliability layer:
    A naive argmax on |dT/dy| is too trusting — a warm hand or edge artifact
    creates a sharp gradient the algorithm mis-reads as a liquid/air interface.
    Before publishing a level we run sanity checks:
      1. Uniformity     — if the strip's temperature span is below 1.5x the
                          confidence gate, there is no interface to find →
                          reliability="uniform", level_pct=null (the UI
                          renders "--"; we can't tell "empty" from "full of
                          uniformly-heated liquid" without a reference).
      2. Step quality   — require the "above" and "below" halves of the
                          interface to be internally uniform (low std) AND
                          differ in mean by at least the gate. Hand blobs
                          fail this because the "above" region is noisy.
                          Also catches legitimate-looking 100% / 0% tanks
                          from spurious top/bottom-row artifacts.
      3. Temporal MAD   — reject peaks that deviate > 3*MAD from the median
                          of the last N frames, snap to the stable level.
    When any check fails we still return a result (so the UI has something
    to render) but with reliability != "ok" and level_pct = last_stable.

v1.10 multi-phase detection (Gas / Oil / Water):
    Oil storage tanks routinely stratify into three thermal bands: a cold
    gas headspace, an oil column, and a warmer (or colder, depending on
    process) water cut at the bottom. The gradient profile shows TWO
    distinct peaks instead of one. We now extract up to 3 interfaces
    (= 4 phases) by finding all local maxima above an absolute + relative
    floor with a minimum separation. ``phases`` in the result is the
    top-to-bottom list of bands with ``label`` (gas / oil / water / …),
    ``pct_top``, ``pct_bottom``, ``thickness_pct`` and ``temp_mean``.
    ``level_pct`` stays backward-compatible: it points at the topmost
    interface (= top of the first liquid band from the top).
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

# --- v1.10 reliability tuning -------------------------------------------
# A strip whose temperature span is below this many × the per-tank min
# temp delta is considered "uniform" (no interface present). We report
# level_pct=null + reliability="uniform" rather than forcing 0% — an arm
# filling an ROI, a uniformly heated tank and an empty tank all look
# uniform, and we have no reference to tell them apart.
UNIFORM_SPAN_MULTIPLIER = 1.5
# For the step-quality test: require the "above" and "below" region means
# to differ by at least this many times the per-tank gate. This is the
# replacement for the old edge_clip heuristic — a peak at row 0 is fine
# if the step across it is meaningful (legit 100% tank) and rejected if
# not (edge artifact from a warm body outside the tank).
STEP_DELTA_MIN_MULTIPLIER = 0.6
# For the step-quality test: each half's std dev must be below this
# fraction of the full strip span (kind of a Otsu-lite coherence score).
STEP_STDEV_FRAC_MAX = 0.45
# Temporal MAD: reject a peak row that moves by more than this many MADs
# from the rolling median over the last N frames.
TEMPORAL_MAD_K = 3.0
TEMPORAL_WINDOW = 7

# --- v1.10 multi-phase tuning -------------------------------------------
# Peaks must exceed (MULTI_PEAK_ABS_FLOOR_MULT × min_temp_delta) in
# absolute gradient magnitude AND must be at least MULTI_PEAK_REL_FLOOR ×
# primary_peak_magnitude to be reported as an additional interface. This
# keeps imaging noise from producing spurious oil/water layers.
MULTI_PEAK_ABS_FLOOR_MULT = 0.8
MULTI_PEAK_REL_FLOOR = 0.35
# Minimum row separation between two peaks, expressed as a fraction of
# the ROI height. 8% avoids picking two rows that describe the same
# physical interface because of gradient smoothing.
MULTI_PEAK_MIN_SEP_FRAC = 0.08
# Cap on the number of interfaces we return — 3 interfaces = 4 bands,
# which covers foam + gas + oil + water. Beyond that the operator is
# looking at noise or a very unusual tank.
MULTI_PEAK_MAX_COUNT = 3


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
        # v1.8: per-tank history of the raw peak row (0..roi_h-1) so we can
        # compute a temporal MAD and reject single-frame outliers. Uses a
        # larger window than level_hist because peaks are noisier than the
        # already-smoothed level_pct.
        self._peak_hist: dict[str, deque[int]] = {
            t["id"]: deque(maxlen=TEMPORAL_WINDOW) for t in tanks_config
        }
        # v1.8: last "good" (reliability=="ok") reading per tank, used as
        # the fallback when the current frame is flagged uncertain so the
        # UI still shows a stable number instead of NaN.
        self._last_good: dict[str, dict[str, Any]] = {}
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

    def _find_peaks(
        self,
        grad: np.ndarray,
        min_delta: float,
    ) -> list[int]:
        """Return up to ``MULTI_PEAK_MAX_COUNT`` peak row indices, sorted
        top→bottom.

        Peaks are ranked by gradient magnitude, then accepted greedily so
        long as each new peak is at least ``MULTI_PEAK_MIN_SEP_FRAC`` × n
        away from every previously-accepted peak and clears the absolute
        and relative magnitude floors.
        """
        n = int(grad.size)
        if n < 5:
            return []
        min_sep = max(3, int(n * MULTI_PEAK_MIN_SEP_FRAC))
        abs_floor = MULTI_PEAK_ABS_FLOOR_MULT * min_delta
        order = np.argsort(grad)[::-1]
        picked: list[int] = []
        primary_val: float | None = None
        for i in order:
            v = float(grad[i])
            if v < abs_floor:
                break
            if primary_val is None:
                primary_val = v
            elif v < MULTI_PEAK_REL_FLOOR * primary_val:
                break
            if all(abs(int(i) - p) >= min_sep for p in picked):
                picked.append(int(i))
                if len(picked) >= MULTI_PEAK_MAX_COUNT:
                    break
        picked.sort()
        return picked

    @staticmethod
    def _label_bands(count: int) -> list[str]:
        """Assign human-friendly labels to top→bottom bands by count.

        We don't know whether the liquid above is hotter or colder than the
        liquid below — the UI colors each band by its own temperature and
        lets the operator read it. Labels are purely positional and match
        the conventional order in oil storage: gas → oil → water.
        """
        if count <= 1:
            return ["uniform"] if count == 1 else []
        if count == 2:
            return ["gas", "liquid"]
        if count == 3:
            return ["gas", "oil", "water"]
        labels = ["gas"] + [f"layer_{i}" for i in range(1, count - 1)] + ["water"]
        return labels

    def _build_phases(
        self,
        profile: np.ndarray,
        peaks: list[int],
    ) -> list[dict[str, Any]]:
        """Build top→bottom band descriptors from the peak list."""
        n = int(profile.size)
        if n == 0:
            return []
        boundaries = [0] + [int(p) for p in peaks] + [n]
        bands: list[dict[str, Any]] = []
        for i in range(len(boundaries) - 1):
            lo = boundaries[i]
            hi = boundaries[i + 1]
            if hi <= lo:
                continue
            sub = profile[lo:hi]
            bands.append(
                {
                    "pct_top": round(lo / n * 100.0, 1),
                    "pct_bottom": round(hi / n * 100.0, 1),
                    "thickness_pct": round((hi - lo) / n * 100.0, 1),
                    "temp_mean": round(float(sub.mean()), 2),
                    "temp_min": round(float(sub.min()), 2),
                    "temp_max": round(float(sub.max()), 2),
                }
            )
        labels = self._label_bands(len(bands))
        for b, label in zip(bands, labels):
            b["label"] = label
        return bands

    def _reliability_check(
        self,
        tank_id: str,
        profile: np.ndarray,
        grad: np.ndarray,
        peak_idx: int,
        peak_val: float,
        min_delta: float,
    ) -> dict[str, Any]:
        """Run the v1.10 sanity checks on a candidate interface.

        Returns a dict with:
            reliability : "ok" | "uniform" | "uncertain"
            reasons     : list of failed-check names (empty when ok)
            effective_peak_idx : peak row to use downstream (may be the
                                 rolling median when temporal MAD fires).

        v1.10 drops the standalone edge_clip rule — a peak at row 0 or
        row n-1 is now accepted if the step across it is meaningful
        (legitimate 100% or 0% tank). If the "above" half of a top-edge
        peak is noisy or the step is weak, step-quality catches it.
        """
        reasons: list[str] = []
        n = int(profile.size)
        strip_span = float(profile.max() - profile.min())

        # 1. Uniformity — if the whole ROI is uniform in temperature there
        #    is no interface to find. Previously we forced level=0 with
        #    reliability="empty"; now we return null so the UI can render
        #    "--" rather than a lie. An operator who legitimately has an
        #    empty tank will see "Uniform ROI — no interface" and can
        #    pair that with the temperature readings to confirm.
        if strip_span < UNIFORM_SPAN_MULTIPLIER * min_delta:
            return {
                "reliability": "uniform",
                "reasons": ["uniform_roi"],
                "effective_peak_idx": peak_idx,
                "strip_span": strip_span,
            }

        # 2. Step quality — a real liquid interface separates the profile
        #    into two internally-uniform halves with a meaningful mean
        #    delta. Hand blobs and localized hot spots fail this because
        #    the "above" half is noisy. This check now applies regardless
        #    of edge position, absorbing the v1.8 edge_clip heuristic.
        #    For edge peaks we look at the big side only (the small side
        #    is too short to be statistically meaningful).
        if 1 <= peak_idx <= n - 2:
            above = profile[:peak_idx] if peak_idx >= 2 else None
            below = profile[peak_idx:] if (n - peak_idx) >= 2 else None
            if above is not None and below is not None:
                step_delta = abs(float(below.mean() - above.mean()))
                max_std = max(float(above.std()), float(below.std()))
                if step_delta < STEP_DELTA_MIN_MULTIPLIER * min_delta:
                    reasons.append("weak_step")
                if strip_span > 0 and (max_std / strip_span) > STEP_STDEV_FRAC_MAX:
                    reasons.append("noisy_halves")
            else:
                # Peak within 1 row of either edge — look at the long side
                # only. Accept if it's internally uniform.
                long_side = below if above is None else above
                if long_side is not None and long_side.size >= 3:
                    if strip_span > 0 and (float(long_side.std()) / strip_span) > STEP_STDEV_FRAC_MAX:
                        reasons.append("noisy_halves")

        # 3. Temporal MAD — a real liquid level moves over seconds; single-
        #    frame spikes (somebody waved a hand past) get clamped to the
        #    rolling median of the last N peaks.
        hist = self._peak_hist.setdefault(tank_id, deque(maxlen=TEMPORAL_WINDOW))
        effective = peak_idx
        if len(hist) >= 3:
            med = float(np.median(hist))
            mad = float(np.median(np.abs(np.array(hist, dtype=np.float32) - med))) or 1.0
            if abs(peak_idx - med) > TEMPORAL_MAD_K * mad:
                reasons.append("temporal_spike")
                effective = int(round(med))
        hist.append(int(peak_idx))

        reliability = "uncertain" if reasons else "ok"
        return {
            "reliability": reliability,
            "reasons": reasons,
            "effective_peak_idx": effective,
            "strip_span": strip_span,
        }

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
            n = len(profile)
            min_delta = float(t.get("min_temp_delta", 1.0))

            # --- v1.10 multi-peak detection ----------------------------
            # Find up to 3 real interfaces (= 4 phases). When the tank is
            # uniform or the gradient is below the noise floor, `peaks`
            # is empty and we fall back to np.argmax for the reliability
            # check so the operator still gets a diagnostic row_idx.
            peaks = self._find_peaks(grad, min_delta)
            if peaks:
                peak_idx_raw = peaks[0]
            else:
                peak_idx_raw = int(np.argmax(grad))
            peak_val = float(grad[peak_idx_raw])

            # --- reliability layer -------------------------------------
            # Before trusting peak_idx, check for uniform-ROI, bad step
            # shape, and temporal spikes.
            rel = self._reliability_check(
                tank_id=t["id"],
                profile=profile,
                grad=grad,
                peak_idx=peak_idx_raw,
                peak_val=peak_val,
                min_delta=min_delta,
            )
            reliability = rel["reliability"]
            reliability_reasons = rel["reasons"]
            peak_idx = int(rel["effective_peak_idx"])

            # v1.10: when ROI is uniform we refuse to guess a level —
            # an empty tank and a uniformly-heated full tank look the
            # same from a single vertical strip.
            if reliability == "uniform":
                level_pct = None
            else:
                level_pct = (n - peak_idx) / n * 100.0
                if self.invert:
                    level_pct = 100.0 - level_pct

            hist = self._level_hist.setdefault(t["id"], deque(maxlen=5))

            level_stable: float | None
            if reliability == "uncertain":
                # Don't pollute the median with garbage frames — fall back
                # to the last known-good reading if we have one.
                last_good = self._last_good.get(t["id"])
                if last_good is not None:
                    level_stable = float(last_good["level_pct"])
                    peak_idx = int(last_good["peak_idx"])
                    level_pct = level_stable
                else:
                    # No history yet (cold start, or never had an OK
                    # frame): we refuse to make up a number.
                    level_stable = None
            elif reliability == "uniform":
                # Uniform ROI — no interface to track, no history to
                # update. UI renders "--".
                level_stable = None
            else:
                # ok: fold into median history AND update last_good.
                assert level_pct is not None
                hist.append(level_pct)
                level_stable = float(np.median(hist))
                self._last_good[t["id"]] = {
                    "level_pct": level_stable,
                    "peak_idx": peak_idx,
                }

            # v1.10: phase bands — top→bottom list of {label, pct_top,
            # pct_bottom, thickness_pct, temp_mean}. 1 band when uniform
            # or single-peak low-quality, 2+ when real interfaces found.
            phases = self._build_phases(profile, peaks)

            # Confidence still tracks the gradient gate — it's a strictly
            # narrower signal than reliability. A frame can have high
            # confidence (strong gradient) but still be uncertain (edge
            # artifact in the top row).
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
            if geometry is not None and level_stable is not None:
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

            # Alarms require a real level; null level means "no reading" so
            # clear any pending alarm state for this tank.
            alarms_state = (
                self._alarms_state(t, level_stable)
                if level_stable is not None
                else {"hi": False, "lo": False, "hi_pct": None, "lo_pct": None}
            )

            results.append(
                {
                    "id": t["id"],
                    "name": t["name"],
                    "topic": t.get("topic"),
                    "medium": medium,
                    "medium_declared": declared_medium or None,
                    "medium_confidence": classification.confidence,
                    "medium_features": classification.features,
                    "level_pct": round(level_stable, 1) if level_stable is not None else None,
                    "level_pct_raw": round(level_pct, 1) if level_pct is not None else None,
                    "temp_min": round(float(strip.min()), 2),
                    "temp_max": round(float(strip.max()), 2),
                    "temp_avg": round(mean_inside, 2),
                    "gradient_peak": round(peak_val, 3),
                    "interface_row": peak_idx,
                    "interface_row_sensor": interface_row_sensor,
                    "confidence": confidence,
                    "reliability": reliability,
                    "reliability_reasons": reliability_reasons,
                    "roi": r,
                    "geometry": _geometry_dict(geometry) if geometry else None,
                    "reading": reading_dict,
                    "alarms": alarms_state,
                    "layers": layers,
                    "phases": phases,
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
        min_delta = float(t.get("min_temp_delta", 1.0))
        # v1.10: run the same multi-peak pipeline the analyze() call uses so
        # the Why modal surfaces the exact same interface rows and phase
        # bands the main card shows.
        peaks = self._find_peaks(grad, min_delta)
        peak_idx = peaks[0] if peaks else int(np.argmax(grad))
        peak_val = float(grad[peak_idx])
        # Re-run the reliability check so the Why modal can surface the same
        # reasons the analyzer used. Does not mutate history (that's the
        # analyze() call's job).
        saved_hist = list(self._peak_hist.get(t["id"], ()))
        rel = self._reliability_check(
            tank_id=t["id"],
            profile=profile,
            grad=grad,
            peak_idx=peak_idx,
            peak_val=peak_val,
            min_delta=min_delta,
        )
        # Restore history — analyze_detailed is a read-only diagnostic path
        # and should not influence the temporal MAD.
        self._peak_hist[t["id"]] = deque(saved_hist, maxlen=TEMPORAL_WINDOW)
        phases = self._build_phases(profile, peaks)
        return {
            "id": t["id"],
            "roi": r,
            "profile": [round(float(v), 3) for v in profile],
            "gradient": [round(float(v), 4) for v in grad],
            "peak_idx": peak_idx,
            "peaks": [int(p) for p in peaks],
            "peak_val": round(peak_val, 4),
            "min_temp_delta": min_delta,
            "roi_height": int(strip.shape[0]),
            "y0": y0,
            "reliability": rel["reliability"],
            "reliability_reasons": rel["reasons"],
            "strip_span": round(float(rel["strip_span"]), 3),
            "phases": phases,
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
