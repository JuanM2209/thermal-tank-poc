"""Fill/drain rate estimator with outlier rejection.

Method
------
- Hold a rolling window of (timestamp, volume_bbl) samples for each tank.
- Drop samples older than `window_seconds` (default 5 min).
- Reject single-point outliers with a Hampel filter (|x - median| > k * MAD).
- Rate = slope of a least-squares linear fit through the surviving samples.
- Emit `minutes_to_full` / `minutes_to_empty` only when the rate has kept a
  stable sign for `stable_sign_seconds` (default 2 min).
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass

HAMPEL_K: float = 3.0
MAD_SCALE: float = 1.4826
DEFAULT_WINDOW_SECONDS: float = 300.0
DEFAULT_STABLE_SIGN_SECONDS: float = 120.0


@dataclass(frozen=True)
class RateSnapshot:
    fill_rate_bbl_h: float          # positive = filling, negative = draining
    minutes_to_full: float | None
    minutes_to_empty: float | None
    samples_used: int


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    return s[n // 2] if n % 2 else 0.5 * (s[n // 2 - 1] + s[n // 2])


def _hampel_keep(values: list[float], k: float = HAMPEL_K) -> list[bool]:
    if len(values) < 5:
        return [True] * len(values)
    m = _median(values)
    deviations = [abs(v - m) for v in values]
    mad = _median(deviations) * MAD_SCALE
    if mad == 0:
        return [True] * len(values)
    threshold = k * mad
    return [abs(v - m) <= threshold for v in values]


def _linear_slope(ts: list[float], vs: list[float]) -> float:
    """Slope of least-squares fit (units: v per t). Zero if degenerate."""
    n = len(ts)
    if n < 2:
        return 0.0
    mean_t = sum(ts) / n
    mean_v = sum(vs) / n
    num = sum((t - mean_t) * (v - mean_v) for t, v in zip(ts, vs))
    den = sum((t - mean_t) ** 2 for t in ts)
    return num / den if den else 0.0


class RateEstimator:
    """Per-tank rate estimator. One instance per tank id."""

    def __init__(
        self,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        stable_sign_seconds: float = DEFAULT_STABLE_SIGN_SECONDS,
    ):
        self.window_seconds = window_seconds
        self.stable_sign_seconds = stable_sign_seconds
        self._samples: deque[tuple[float, float]] = deque()
        self._last_sign: int = 0         # -1, 0, +1
        self._sign_since: float = 0.0

    def push(self, volume_bbl: float, now: float | None = None) -> None:
        ts = time.time() if now is None else now
        self._samples.append((ts, float(volume_bbl)))
        self._trim(ts)

    def _trim(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()

    def snapshot(
        self,
        geometry_volume_full_bbl: float,
        current_volume_bbl: float,
        now: float | None = None,
    ) -> RateSnapshot:
        if now is None:
            now = time.time()
        self._trim(now)
        if len(self._samples) < 3:
            return RateSnapshot(0.0, None, None, len(self._samples))

        times = [t for t, _ in self._samples]
        vols = [v for _, v in self._samples]
        keep = _hampel_keep(vols)
        t_clean = [t for t, ok in zip(times, keep) if ok]
        v_clean = [v for v, ok in zip(vols, keep) if ok]
        if len(v_clean) < 3:
            return RateSnapshot(0.0, None, None, len(v_clean))

        slope_per_s = _linear_slope(t_clean, v_clean)
        rate_per_h = slope_per_s * 3600.0

        # Track sign stability.
        sign = 0 if abs(rate_per_h) < 1e-3 else (1 if rate_per_h > 0 else -1)
        if sign != self._last_sign:
            self._last_sign = sign
            self._sign_since = now
        stable = (now - self._sign_since) >= self.stable_sign_seconds and sign != 0

        mins_full: float | None = None
        mins_empty: float | None = None
        if stable:
            if sign > 0:
                remaining = max(0.0, geometry_volume_full_bbl - current_volume_bbl)
                mins_full = remaining / rate_per_h * 60.0 if rate_per_h > 0 else None
            elif sign < 0:
                remaining = max(0.0, current_volume_bbl)
                mins_empty = remaining / abs(rate_per_h) * 60.0

        return RateSnapshot(
            fill_rate_bbl_h=round(rate_per_h, 2),
            minutes_to_full=round(mins_full, 0) if mins_full is not None else None,
            minutes_to_empty=round(mins_empty, 0) if mins_empty is not None else None,
            samples_used=len(v_clean),
        )

    def reset(self) -> None:
        self._samples.clear()
        self._last_sign = 0
        self._sign_since = 0.0
