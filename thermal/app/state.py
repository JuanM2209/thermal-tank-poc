"""Process-wide shared state between the capture/analysis loop and the web API.

Only one producer (main loop), many consumers (Flask threads), so a simple
lock-guarded mutable container is enough — no ring buffer, no queues.
"""

from __future__ import annotations

import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Latest:
    ts: float = 0.0
    frame_idx: int = 0
    thermal: Any = None           # HxW float32 °C (sensor resolution)
    visual: Any = None            # HxWx3 uint8 BGR
    rendered: Any = None          # HxWx3 uint8 BGR (palette + overlay + upscale)
    rendered_upscale: int = 1
    tmin: float = 0.0
    tmax: float = 0.0
    hot: tuple | None = None      # (x, y, °C) in sensor coords
    cold: tuple | None = None
    results: list = field(default_factory=list)
    fps: float = 0.0
    # Non-critical diagnostic signals surfaced to the UI. rotate_hint is a
    # gentle nudge ("thermal gradient is stronger horizontally — try rotating
    # 90°") that the web UI can surface as a banner.
    rotate_hint: dict | None = None


class SharedState:
    def __init__(self):
        self._lock = threading.Lock()
        self._latest = Latest()
        self._cfg_version = 0
        self._events: list = []
        self._event_seq = 0

    # ---- writer side ---------------------------------------------------------
    def publish(self, *, thermal, visual, rendered, rendered_upscale, tmin, tmax,
                hot, cold, results, fps, frame_idx, rotate_hint=None):
        with self._lock:
            self._latest = Latest(
                ts=time.time(),
                frame_idx=frame_idx,
                thermal=thermal,
                visual=visual,
                rendered=rendered,
                rendered_upscale=rendered_upscale,
                tmin=tmin, tmax=tmax,
                hot=hot, cold=cold,
                results=results,
                fps=fps,
                rotate_hint=rotate_hint,
            )

    def append_event(self, kind: str, **payload):
        with self._lock:
            self._event_seq += 1
            self._events.append({
                "seq": self._event_seq,
                "ts": time.time(),
                "kind": kind,
                **payload,
            })
            # keep recent 200
            if len(self._events) > 200:
                self._events = self._events[-200:]

    def bump_cfg(self):
        with self._lock:
            self._cfg_version += 1

    # ---- reader side ---------------------------------------------------------
    def snapshot(self):
        with self._lock:
            return self._latest

    def events_since(self, seq: int = 0, limit: int = 50):
        with self._lock:
            return [e for e in self._events if e["seq"] > seq][-limit:]

    @property
    def cfg_version(self) -> int:
        with self._lock:
            return self._cfg_version


SHARED = SharedState()


class PerfStats:
    """Lock-guarded per-stage latency + capture telemetry snapshot for /api/stats.

    Single writer (main loop), many readers (Flask). Holds the most recent
    50-frame window of average stage times (ms) so the dashboard can see
    exactly which stage is eating the frame budget.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_window: dict[str, Any] = {
            "window_ts": 0.0,
            "window_frames": 0,
            "fps": 0.0,
            "frame_idx": 0,
            "stage_ms_avg": {},
            "cap": {},
            "reader": {},
        }

    def record_window(
        self,
        *,
        stage_ms_avg: dict[str, float],
        fps: float,
        frame_idx: int,
        cap_stats: dict[str, Any] | None,
        reader_stats: dict[str, Any] | None,
    ) -> None:
        with self._lock:
            self._last_window = {
                "window_ts": time.time(),
                "window_frames": 50,
                "fps": round(float(fps), 3),
                "frame_idx": int(frame_idx),
                "stage_ms_avg": {k: round(float(v), 3) for k, v in stage_ms_avg.items()},
                "cap": deepcopy(cap_stats or {}),
                "reader": deepcopy(reader_stats or {}),
            }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._last_window)


PERF = PerfStats()
