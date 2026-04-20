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

v1.11 Otsu contrast-first level detector:
    The v1.10 gradient-peak detector fails on heterogeneous scenes that
    don't have a clean horizontal liquid/gas interface — a rectangle drawn
    over a wall, a warm hand or a water bottle placed inside the ROI. Any
    gradient noise produced *some* argmax and the tank reported a bogus
    level (typically 100 %).

    v1.11 replaced the primary level estimate with a 2-class pixel
    classifier + three uniform gates.

v1.12 Physics-correct height + temporal smoothing (v0.9.0 release):
    Field testing of v1.11 surfaced three failure modes of the pixel-area
    estimator:
      • A 5 %-area warm bottle mid-ROI produced a 35 % reading because
        ``level_pct = 100 × liquid_pixel_fraction`` counts area, not height.
      • The reading jittered ±3 % between frames on a static scene because
        per-frame Otsu picks a new threshold bin each time.
      • An object in the middle of the ROI was indistinguishable from a
        partially-filled tank — both give the same liquid fraction.

    v1.12 fixes all three by imposing the physics of a liquid column:
      1. Row-majority interface row — the top-most ROI row whose
         liquid-pixel fraction crosses 0.5. ``level_pct`` is now the
         fraction of rows *below* that row, i.e. true column height, not
         pixel area. A 5 %-area bottle in the middle now reads as empty
         unless the bottle rows themselves are majority-liquid AND the
         rows below them are too.
      2. EMA-smoothed Otsu threshold T* (α = 0.15). The per-frame Otsu
         split is noisy — we blend it 15 % / 85 % with the prior frame so
         frame-to-frame jitter is < 0.5 % in a static scene while the
         reading still responds to a genuine level change within ~0.5 s.
      3. Monotonicity gate. A real liquid column has more liquid below
         the interface than above it. We compute
         ``monotonicity = below_rows_mean − above_rows_mean`` and refuse
         the reading (``reliability="uniform"``, reason
         ``low_monotonicity``) when it falls below 0.35 — this is the
         signature of an object suspended in the middle of the ROI with
         no liquid below it.

    The v1.10 gradient peaks are still computed for the `phases[]` band
    list (used for stratified-tank overlays), so real oil/water tanks
    that happen to show clean interfaces continue to get labelled bands.
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

# --- v1.11 Otsu contrast-first tuning -----------------------------------
# Between-class variance ratio (η ∈ [0,1]) below this => histogram is
# effectively unimodal and we refuse to guess a level. 0.3 is the empirical
# sweet spot: near-0 for uniform walls, > 0.5 for a real hand/bottle, > 0.7
# for a clean tank interface.
OTSU_ETA_MIN = 0.3
# Strict contrast floor. An ROI spanning less than this many °C is declared
# uniform even if Otsu finds a technically optimal split (the split is
# dominated by sensor noise at that point).
OTSU_CONTRAST_MIN_C = 2.0
# Std-dev floor. Catches ROIs with one outlier bright pixel in an otherwise
# uniform scene — those can clear the span gate but not this one.
OTSU_STDDEV_MIN_C = 0.5
# Fraction of the bottom rows used to auto-detect liquid polarity. If the
# mean of the bottom 20 % of rows is below the Otsu threshold, the cold
# class is declared "liquid"; else the warm class.
OTSU_BOTTOM_WINDOW_FRAC = 0.2
# Number of histogram bins used for the Otsu search. 64 is enough precision
# for a typical 5-40 °C scene without being sensitive to noise.
OTSU_HIST_BINS = 64

# --- v1.12 physics + temporal tuning ------------------------------------
# EMA α for the per-frame Otsu threshold. 0.15 gives ~170 ms response at
# 30 fps — fast enough for a genuine level change but kills the 1-bin
# histogram jitter that v1.11 exhibited on a static scene.
OTSU_EMA_ALPHA = 0.15
# Monotonicity score floor. below_rows_mean − above_rows_mean must clear
# this for the reading to count. A hand / bottle suspended mid-ROI with
# no liquid below it has a low below-fill → score ≈ 0.35 or less → rejected.
# A genuine 50 % tank scores ~0.9, a 5 % tank scores ~0.65, so 0.5 is a
# comfortable floor that catches objects while accepting realistic fills.
MONOTONICITY_MIN = 0.5
# Row-interface crossover threshold. Interface row = first row from the
# top whose smoothed liquid fraction ≥ this value. 0.5 is the natural
# majority-vote level.
ROW_INTERFACE_THRESHOLD = 0.5
# 1-D smoothing kernel length for the per-row liquid fraction before the
# crossover search. 3 rows is enough to kill isolated noisy rows without
# shifting a real interface by more than one row.
ROW_SMOOTH_KERNEL = 3


def _smooth_rows(rows: np.ndarray, k: int = ROW_SMOOTH_KERNEL) -> np.ndarray:
    """Centred moving-average over a 1-D vector with edge preservation."""
    n = int(rows.size)
    if n == 0 or k <= 1:
        return rows.astype(np.float32, copy=True)
    k = min(k, n)
    kern = np.ones(k, dtype=np.float32) / float(k)
    return np.convolve(rows.astype(np.float32), kern, mode="same")


def _find_interface_row(liq_rows: np.ndarray) -> int:
    """Find the top-most row whose smoothed liquid fraction ≥ threshold.

    Returns the row index in [0, n] (n when no row crosses → empty ROI).
    """
    n = int(liq_rows.size)
    if n == 0:
        return 0
    above = liq_rows >= ROW_INTERFACE_THRESHOLD
    idx = np.where(above)[0]
    if idx.size == 0:
        return n  # nothing majority-liquid → tank reads empty
    return int(idx[0])


def _otsu_threshold_eta(pixels: np.ndarray) -> tuple[float, float]:
    """Compute an Otsu split on ``pixels`` (1-D flattened temperatures).

    Returns
    -------
    threshold : float
        Temperature in °C that maximizes between-class variance.
    eta : float
        Normalized between-class variance ∈ [0, 1]. 1 = perfectly bimodal,
        0 = no class separation (uniform ROI).
    """
    flat = pixels.ravel().astype(np.float32)
    if flat.size == 0:
        return 0.0, 0.0
    tmin, tmax = float(flat.min()), float(flat.max())
    if tmax - tmin < 1e-6:
        return 0.5 * (tmin + tmax), 0.0
    hist, edges = np.histogram(flat, bins=OTSU_HIST_BINS, range=(tmin, tmax))
    total = int(hist.sum())
    if total == 0:
        return 0.5 * (tmin + tmax), 0.0
    mids = 0.5 * (edges[:-1] + edges[1:])
    p = hist.astype(np.float64) / float(total)
    cum_p = np.cumsum(p)
    cum_m = np.cumsum(p * mids)
    total_mean = float(cum_m[-1])
    # σ_B²(t) = (total_mean·ω(t) − μ(t))² / (ω(t)·(1 − ω(t)))
    with np.errstate(divide="ignore", invalid="ignore"):
        num = (total_mean * cum_p - cum_m) ** 2
        den = cum_p * (1.0 - cum_p)
        sigma_b_sq = np.where(den > 1e-12, num / den, 0.0)
    i = int(np.argmax(sigma_b_sq))
    threshold = float(mids[i])
    sigma_b_max = float(sigma_b_sq[i])
    var_total = float(flat.var())
    eta = sigma_b_max / var_total if var_total > 1e-9 else 0.0
    return threshold, float(max(0.0, min(1.0, eta)))


def _otsu_level(
    strip: np.ndarray,
    liquid_is_cold: bool | None,
    prev_threshold: float | None = None,
) -> dict[str, Any]:
    """2-class pixel classifier + row-majority interface detector.

    v1.12 changes from v1.11:
        • ``level_pct`` is derived from the row-majority interface
          row (liquid column height), not from the pixel-area fraction.
        • An EMA is applied to the Otsu threshold when ``prev_threshold``
          is supplied. This is the dominant jitter-reduction mechanism
          for a static scene.
        • ``monotonicity`` is reported so the caller can refuse readings
          where there is no liquid below the declared interface.

    Parameters
    ----------
    strip : 2-D array of °C values (rows top→bottom, cols left→right).
    liquid_is_cold : True forces cold=liquid, False forces warm=liquid,
        None auto-detects from the bottom of the ROI.
    prev_threshold : previous frame's EMA-smoothed Otsu threshold in °C,
        or None on the first frame. The returned ``threshold_c`` has the
        EMA already applied so the caller just feeds it back next frame.

    Returns a dict with:
        threshold_c            : EMA-smoothed Otsu split temperature
        threshold_c_raw        : raw per-frame Otsu split (no EMA)
        eta                    : between-class variance ratio ∈ [0, 1]
        liquid_is_cold         : resolved polarity (True/False)
        liquid_is_cold_auto    : whether polarity was auto-detected
        liquid_fraction        : fraction of ROI pixels classified liquid
        liquid_fraction_rows   : smoothed per-row liquid fraction
        level_row              : row index of the liquid/gas interface
                                 (top-most row where smoothed liquid
                                 fraction ≥ 0.5)
        level_pct              : 100 × (h − level_row) / h
        monotonicity           : below_rows.mean − above_rows.mean. A
                                 genuine liquid column has this ≥ ~0.5;
                                 an object in the middle has it ≤ 0.
    """
    h, w = strip.shape
    flat = strip.astype(np.float32).ravel()
    threshold_raw, eta = _otsu_threshold_eta(flat)

    # --- EMA smoothing of the threshold (kills per-frame bin jitter) -
    # We only blend when the raw threshold has not drifted by a huge
    # amount from the prior — if it has, the scene genuinely changed and
    # we want to snap. 10 °C is far larger than thermal noise and far
    # smaller than a realistic scene-swap, so it is the clean threshold.
    if prev_threshold is None or abs(threshold_raw - prev_threshold) > 10.0:
        threshold = float(threshold_raw)
    else:
        threshold = float(
            OTSU_EMA_ALPHA * threshold_raw + (1.0 - OTSU_EMA_ALPHA) * prev_threshold
        )

    # --- auto-detect polarity from bottom rows -----------------------
    auto_bool = False
    if liquid_is_cold is None:
        auto_bool = True
        bottom_n = max(1, int(round(h * OTSU_BOTTOM_WINDOW_FRAC)))
        bottom_mean = float(strip[h - bottom_n :].mean())
        liquid_is_cold = bool(bottom_mean <= threshold)

    if liquid_is_cold:
        mask = strip < threshold
    else:
        mask = strip > threshold

    liquid_fraction = float(mask.mean()) if mask.size else 0.0
    liquid_rows_raw = mask.mean(axis=1).astype(np.float32)
    liquid_rows = _smooth_rows(liquid_rows_raw)

    # --- row-majority interface row + height-based level -------------
    level_row = _find_interface_row(liquid_rows)
    level_pct = 100.0 * max(0, (h - level_row)) / max(1, h)

    # --- monotonicity score -------------------------------------------
    # Compare liquid density below the declared interface to liquid
    # density above it. A real tank has below ≫ above; a bottle/hand
    # suspended in the middle has below ≈ 0 and above > 0.
    if 0 < level_row < h:
        below_mean = float(liquid_rows[level_row:].mean())
        above_mean = float(liquid_rows[:level_row].mean())
        monotonicity = below_mean - above_mean
    elif level_row <= 0:
        # Interface at row 0 → ROI is entirely liquid. Trivially monotonic.
        monotonicity = float(liquid_rows.mean()) if liquid_rows.size else 1.0
    else:
        # Interface below bottom row → ROI is entirely gas. Also monotonic
        # (nothing above, nothing below) — pass the gate with the
        # "empty" reading.
        monotonicity = 1.0

    return {
        "threshold_c": float(threshold),
        "threshold_c_raw": float(threshold_raw),
        "eta": float(eta),
        "liquid_is_cold": bool(liquid_is_cold),
        "liquid_is_cold_auto": bool(auto_bool),
        "liquid_fraction": float(liquid_fraction),
        "liquid_fraction_rows": liquid_rows,
        "level_pct": float(level_pct),
        "level_row": int(max(0, min(h, level_row))),
        "monotonicity": float(monotonicity),
    }


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
        # v1.12: EMA-smoothed Otsu threshold, per tank. Keys are tank IDs;
        # values are the last smoothed threshold in °C. Absent keys mean
        # the tank has not been analysed yet (first frame uses raw Otsu).
        self._otsu_threshold: dict[str, float] = {}

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
            strip_span = float(strip.max() - strip.min())
            strip_std = float(strip.std())

            # --- v1.10 multi-peak detection (for phase-band display) ---
            # These still run in v1.11 — they populate `phases[]` used for
            # the stratification overlay when a real oil/water tank shows
            # clean horizontal interfaces. The primary level signal now
            # comes from the Otsu classifier below, not from these peaks.
            peaks = self._find_peaks(grad, min_delta)
            if peaks:
                peak_idx_grad = peaks[0]
            else:
                peak_idx_grad = int(np.argmax(grad))
            peak_val = float(grad[peak_idx_grad])
            phases = self._build_phases(profile, peaks)

            # --- v1.12 Otsu + row-majority classifier (primary level) --
            # Default polarity is auto — the config can pin it per tank
            # with `liquid_is_cold: true|false` when the operator knows.
            polarity_cfg = t.get("liquid_is_cold")
            polarity_override = (
                bool(polarity_cfg) if isinstance(polarity_cfg, bool) else None
            )
            prev_threshold = self._otsu_threshold.get(t["id"])
            otsu = _otsu_level(strip, polarity_override, prev_threshold)
            # Persist the EMA-smoothed threshold for the next frame so
            # jitter keeps dropping over time.
            self._otsu_threshold[t["id"]] = float(otsu["threshold_c"])
            otsu_eta = float(otsu["eta"])
            otsu_monotonicity = float(otsu["monotonicity"])

            # --- v1.12 uniform gates (any failure => no level reported) -
            # 1. low_contrast    — ROI temp span too small for a real interface
            # 2. low_stddev      — single hot pixel pretending to be contrast
            # 3. weak_bimodality — histogram effectively unimodal (η below floor)
            # 4. low_monotonicity— liquid not piled at the bottom (object in ROI)
            uniform_reasons: list[str] = []
            if strip_span < OTSU_CONTRAST_MIN_C:
                uniform_reasons.append("low_contrast")
            if strip_std < OTSU_STDDEV_MIN_C:
                uniform_reasons.append("low_stddev")
            if otsu_eta < OTSU_ETA_MIN:
                uniform_reasons.append("weak_bimodality")
            if otsu_monotonicity < MONOTONICITY_MIN:
                uniform_reasons.append("low_monotonicity")

            reliability_reasons: list[str] = []
            level_pct: float | None
            if uniform_reasons:
                # ROI is effectively uniform or physics-violating — refuse
                # to guess. The UI renders "--" and the operator can read
                # the temperatures directly to decide if the tank is
                # full-of-cold-liquid or truly empty.
                reliability = "uniform"
                reliability_reasons = uniform_reasons
                level_pct = None
                peak_idx = int(otsu["level_row"])
            else:
                reliability = "ok"
                level_pct = float(otsu["level_pct"])
                if self.invert:
                    level_pct = 100.0 - level_pct
                peak_idx = int(otsu["level_row"])

            # --- Temporal MAD: reject single-frame spikes ---------------
            # A genuine level moves over seconds; a 10+ % jump in one frame
            # is almost always a hand passing through the ROI. Clamp to
            # the rolling median and mark the reading uncertain.
            hist_peak = self._peak_hist.setdefault(
                t["id"], deque(maxlen=TEMPORAL_WINDOW)
            )
            if reliability == "ok" and len(hist_peak) >= 3:
                med = float(np.median(hist_peak))
                mad = float(
                    np.median(
                        np.abs(np.array(hist_peak, dtype=np.float32) - med)
                    )
                ) or 1.0
                if abs(peak_idx - med) > TEMPORAL_MAD_K * mad:
                    reliability = "uncertain"
                    reliability_reasons = ["temporal_spike"]
            if reliability == "ok":
                hist_peak.append(int(peak_idx))

            # --- Stable-level median smoother --------------------------
            hist_level = self._level_hist.setdefault(t["id"], deque(maxlen=5))
            level_stable: float | None
            if reliability == "ok":
                assert level_pct is not None
                hist_level.append(level_pct)
                level_stable = float(np.median(hist_level))
                self._last_good[t["id"]] = {
                    "level_pct": level_stable,
                    "peak_idx": peak_idx,
                }
            elif reliability == "uncertain":
                # Fall back to the last known-good reading so the UI has
                # a stable number to display while the spike dies down.
                last_good = self._last_good.get(t["id"])
                if last_good is not None:
                    level_stable = float(last_good["level_pct"])
                    peak_idx = int(last_good["peak_idx"])
                    level_pct = level_stable
                else:
                    level_stable = None
            else:  # uniform
                level_stable = None

            # Confidence is now anchored to Otsu η rather than the raw
            # gradient magnitude: a "high" confidence frame means the
            # histogram is cleanly bimodal, which is the correct signal
            # to gate level publishing on.
            confidence = "high" if otsu_eta >= OTSU_ETA_MIN else "low"

            # Absolute row inside the sensor frame — the UI needs this to
            # paint the level line on the canvas regardless of where the
            # ROI lives.
            interface_row_sensor = int(y0 + peak_idx)

            # Optional secondary interface (air/liquid is primary; a second
            # peak usually corresponds to a sludge or water-in-oil layer).
            # v1.11: search is anchored to the gradient primary peak so the
            # "avoid neighborhood" logic operates on thermal interfaces, not
            # on the Otsu level row.
            layers: list[dict[str, Any]] | None = None
            if t.get("multi_layer") and level_pct is not None:
                min_sep = max(3, int(n * MULTI_LAYER_MIN_SEP_FRAC))
                floor = peak_val * MULTI_LAYER_REL_FLOOR
                sec_idx = self._find_secondary_peak(
                    grad, peak_idx_grad, min_sep, floor
                )
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
                    secondary_label = (
                        "sludge" if sec_idx > peak_idx_grad else "upper"
                    )
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
                    # v1.12 Otsu + physics fields --------------------------
                    # `eta` is the normalized between-class variance (0..1).
                    # The UI uses it as a "confidence" number — > 0.6 is a
                    # clean interface, 0.3..0.6 is marginal, below = uniform.
                    # `monotonicity` is below_rows_mean − above_rows_mean of
                    # the per-row liquid fraction; a genuine column has
                    # this ≫ 0, an object in the middle has it ≤ 0.
                    "eta": round(otsu_eta, 3),
                    "monotonicity": round(otsu_monotonicity, 3),
                    "otsu_threshold_c": round(float(otsu["threshold_c"]), 2),
                    "otsu_threshold_c_raw": round(float(otsu["threshold_c_raw"]), 2),
                    "liquid_fraction": round(float(otsu["liquid_fraction"]), 3),
                    "liquid_is_cold": bool(otsu["liquid_is_cold"]),
                    "liquid_is_cold_auto": bool(otsu["liquid_is_cold_auto"]),
                    "strip_span_c": round(strip_span, 2),
                    "strip_std_c": round(strip_std, 2),
                    # ----------------------------------------------------
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
        strip_span = float(strip.max() - strip.min())
        strip_std = float(strip.std())
        # v1.10 multi-peak (for the phase bar overlay in the Why modal)
        peaks = self._find_peaks(grad, min_delta)
        peak_idx_grad = peaks[0] if peaks else int(np.argmax(grad))
        peak_val = float(grad[peak_idx_grad])
        phases = self._build_phases(profile, peaks)

        # v1.12 Otsu + row-majority — the primary level signal. Mirrors
        # analyze() so the Why modal shows exactly the same reasoning the
        # live card used. We deliberately do NOT mutate the EMA state
        # here: the Why modal is a read-only peek and should never bias
        # the temporal smoother that analyze() owns.
        polarity_cfg = t.get("liquid_is_cold")
        polarity_override = (
            bool(polarity_cfg) if isinstance(polarity_cfg, bool) else None
        )
        prev_threshold = self._otsu_threshold.get(t["id"])
        otsu = _otsu_level(strip, polarity_override, prev_threshold)
        otsu_eta = float(otsu["eta"])
        otsu_monotonicity = float(otsu["monotonicity"])

        uniform_reasons: list[str] = []
        if strip_span < OTSU_CONTRAST_MIN_C:
            uniform_reasons.append("low_contrast")
        if strip_std < OTSU_STDDEV_MIN_C:
            uniform_reasons.append("low_stddev")
        if otsu_eta < OTSU_ETA_MIN:
            uniform_reasons.append("weak_bimodality")
        if otsu_monotonicity < MONOTONICITY_MIN:
            uniform_reasons.append("low_monotonicity")
        reliability = "uniform" if uniform_reasons else "ok"

        peak_idx = int(otsu["level_row"])
        return {
            "id": t["id"],
            "roi": r,
            "profile": [round(float(v), 3) for v in profile],
            "gradient": [round(float(v), 4) for v in grad],
            "peak_idx": peak_idx,
            "peak_idx_grad": int(peak_idx_grad),
            "peaks": [int(p) for p in peaks],
            "peak_val": round(peak_val, 4),
            "min_temp_delta": min_delta,
            "roi_height": int(strip.shape[0]),
            "y0": y0,
            "reliability": reliability,
            "reliability_reasons": uniform_reasons,
            "strip_span": round(strip_span, 3),
            "strip_std": round(strip_std, 3),
            "eta": round(otsu_eta, 3),
            "monotonicity": round(otsu_monotonicity, 3),
            "otsu_threshold_c": round(float(otsu["threshold_c"]), 2),
            "otsu_threshold_c_raw": round(float(otsu["threshold_c_raw"]), 2),
            "liquid_fraction": round(float(otsu["liquid_fraction"]), 3),
            "liquid_fraction_rows": [
                round(float(v), 3) for v in otsu["liquid_fraction_rows"]
            ],
            "liquid_is_cold": bool(otsu["liquid_is_cold"]),
            "liquid_is_cold_auto": bool(otsu["liquid_is_cold_auto"]),
            "level_pct_raw": round(float(otsu["level_pct"]), 1),
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
