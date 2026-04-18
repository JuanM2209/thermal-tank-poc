"""Snapshots + video recording.

Video file format: AVI with MJPG fourcc (most reliable on ARMv7 headless OpenCV;
no ffmpeg dependency, no libx264, no patent concerns).
Snapshots: PNG.

Files land under:
    {snapshot_dir}/snap_YYYYMMDD_HHMMSS.png
    {recording_dir}/rec_YYYYMMDD_HHMMSS.avi

Both directories live on the host-mounted volume (/app/data by default) so
the user can download them by SCP / portal file browser after the session.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime

import cv2
import numpy as np

log = logging.getLogger("recorder")


class Recorder:
    def __init__(self, snapshot_dir: str = "/app/data/snapshots",
                 recording_dir: str = "/app/data/recordings"):
        self.snapshot_dir = snapshot_dir
        self.recording_dir = recording_dir
        os.makedirs(self.snapshot_dir, exist_ok=True)
        os.makedirs(self.recording_dir, exist_ok=True)
        self._writer: cv2.VideoWriter | None = None
        self._file: str | None = None
        self._lock = threading.Lock()
        self._size: tuple[int, int] | None = None
        self._fps: float = 20.0
        self._frames: int = 0
        self._started_at: float = 0.0

    # ---- snapshots ----
    def snapshot(self, frame: np.ndarray) -> dict:
        if frame is None:
            return {"ok": False, "err": "no-frame"}
        name = datetime.now().strftime("snap_%Y%m%d_%H%M%S_%f")[:-3] + ".png"
        path = os.path.join(self.snapshot_dir, name)
        cv2.imwrite(path, frame)
        size = os.path.getsize(path) if os.path.exists(path) else 0
        log.info(f"snapshot -> {path} ({size} bytes)")
        return {"ok": True, "path": path, "name": name, "bytes": size}

    # ---- video ----
    @property
    def recording(self) -> bool:
        with self._lock:
            return self._writer is not None

    def start(self, frame_size: tuple[int, int], fps: float = 20.0) -> dict:
        with self._lock:
            if self._writer is not None:
                return {"ok": False, "err": "already-recording", "file": self._file}
            w, h = frame_size
            name = datetime.now().strftime("rec_%Y%m%d_%H%M%S") + ".avi"
            path = os.path.join(self.recording_dir, name)
            fourcc = cv2.VideoWriter_fourcc(*"MJPG")
            writer = cv2.VideoWriter(path, fourcc, float(fps), (w, h))
            if not writer.isOpened():
                return {"ok": False, "err": "cannot-open-writer"}
            self._writer = writer
            self._file = path
            self._size = (w, h)
            self._fps = fps
            self._frames = 0
            self._started_at = time.time()
            log.info(f"recording started -> {path} @ {fps} fps ({w}x{h})")
        return {"ok": True, "file": path, "name": name, "fps": fps, "size": [w, h]}

    def write(self, frame: np.ndarray):
        with self._lock:
            if self._writer is None:
                return
            if self._size and (frame.shape[1], frame.shape[0]) != self._size:
                # Resize to the recording size if overlay/upscale changed
                frame = cv2.resize(frame, self._size)
            self._writer.write(frame)
            self._frames += 1

    def stop(self) -> dict:
        with self._lock:
            if self._writer is None:
                return {"ok": False, "err": "not-recording"}
            self._writer.release()
            path = self._file
            duration = time.time() - self._started_at
            frames = self._frames
            self._writer = None
            self._file = None
            size = os.path.getsize(path) if path and os.path.exists(path) else 0
            log.info(f"recording stopped: {path} frames={frames} dur={duration:.1f}s bytes={size}")
            return {"ok": True, "file": path, "name": os.path.basename(path or ""),
                    "frames": frames, "seconds": round(duration, 2), "bytes": size}

    def status(self) -> dict:
        with self._lock:
            if self._writer is None:
                return {"recording": False}
            return {
                "recording": True,
                "file": self._file,
                "frames": self._frames,
                "seconds": round(time.time() - self._started_at, 2),
                "fps": self._fps,
            }

    def list_files(self) -> dict:
        def _list(d):
            try:
                files = sorted(os.listdir(d), reverse=True)
            except OSError:
                return []
            out = []
            for f in files[:100]:
                p = os.path.join(d, f)
                try:
                    st = os.stat(p)
                    out.append({"name": f, "bytes": st.st_size, "mtime": st.st_mtime})
                except OSError:
                    pass
            return out
        return {
            "snapshots": _list(self.snapshot_dir),
            "recordings": _list(self.recording_dir),
        }
