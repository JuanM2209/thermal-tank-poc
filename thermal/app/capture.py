"""
UVC capture for the Thermal Master P2 Pro (and similar Infiray/Xtherm cores).

The camera exposes a YUYV stream where the frame is 2x the sensor height:
  top half   = visual/pseudo-color image (YUYV)
  bottom half = raw thermal data (uint16 per pixel, little-endian)
  raw -> Celsius:  (raw / kelvin_divisor) - 273.15

If this layout does not match your unit, change `decoder` in config.yaml and
the format will be auto-probed at startup (see probe.py).

`ThermalCapture.read()` is a non-blocking call that returns the latest
(visual, thermal) frame pulled by a background thread. This keeps the main
analysis loop insulated from USB / V4L2 hiccups, P2-Pro FFC shutter events,
and any other source of jitter in `cv2.VideoCapture.read()`.
"""

import cv2
import numpy as np
import logging
import threading
import time

log = logging.getLogger("capture")


class ThermalCapture:
    def __init__(self, device="/dev/video0", width=256, height=384, fps=25,
                 decoder="dual_yuyv", kelvin_divisor=64.0,
                 watchdog_timeout_s: float = 4.0):
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.decoder = decoder
        self.kdiv = float(kelvin_divisor)
        self.sensor_h = height // 2 if decoder == "dual_yuyv" else height
        self.cap = None
        self._watchdog_timeout_s = float(watchdog_timeout_s)

        # Background reader state — one slot holding the latest decoded frame
        # pair. Readers never block on V4L2; they get the most recent frame.
        self._lock = threading.Lock()
        self._latest: tuple[np.ndarray, np.ndarray] | None = None
        self._latest_seq: int = 0
        self._consumer_seq: int = 0
        self._last_frame_ts: float = 0.0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Count decode/transport errors so the watchdog can decide to reopen
        self._consecutive_errors: int = 0
        self._reopens: int = 0

    def _open_device(self) -> None:
        cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open {self.device}")

        fourcc = cv2.VideoWriter_fourcc('Y', 'U', 'Y', 'V')
        cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        # Critical: disable automatic RGB conversion so we receive raw YUYV
        cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        cap.set(cv2.CAP_PROP_FPS, self.fps)
        # Keep only the freshest frame — V4L2 buffers add ~200 ms of lag if you
        # let the kernel queue up several frames before you consume one.
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        log.info(f"Opened {self.device} requested {self.width}x{self.height}@{self.fps} -> got {aw}x{ah}")

        # Warm-up — some thermal cores drop the first few frames
        for _ in range(5):
            cap.read()
            time.sleep(0.05)

        self.cap = cap

    def open(self):
        self._open_device()
        self._stop.clear()
        self._last_frame_ts = time.time()
        self._thread = threading.Thread(target=self._reader_loop, name="capture-reader", daemon=True)
        self._thread.start()

    def _split_dual_yuyv(self, raw):
        """
        raw: 1-D or 2-D byte array of size height*width*2.
        Returns (visual_bgr HxWx3 uint8, thermal_celsius HxW float32).
        """
        buf = np.asarray(raw, dtype=np.uint8).reshape(self.height, self.width, 2)

        top = buf[:self.sensor_h]                       # visual YUYV
        bottom = buf[self.sensor_h:]                    # thermal raw

        # Visual: YUYV -> BGR
        visual_bgr = cv2.cvtColor(top, cv2.COLOR_YUV2BGR_YUYV)

        # Thermal: reinterpret byte pairs as little-endian uint16
        thermal_raw = bottom.view(np.uint16).reshape(self.sensor_h, self.width)
        thermal_c = thermal_raw.astype(np.float32) / self.kdiv - 273.15

        return visual_bgr, thermal_c

    def _visual_only(self, raw):
        """Fallback: only the visual frame is usable. Thermal is pseudo-approximated
        from the palette-normalized luminance — useful for ROI setup but not accurate."""
        buf = np.asarray(raw, dtype=np.uint8).reshape(self.height, self.width, 2)
        visual_bgr = cv2.cvtColor(buf, cv2.COLOR_YUV2BGR_YUYV)
        gray = cv2.cvtColor(visual_bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
        # Pseudo-temp in arbitrary units — gradient detection still works
        thermal_c = gray
        return visual_bgr, thermal_c

    def _reader_loop(self) -> None:
        """Background thread: read from V4L2, decode, park the newest frame
        in a 1-slot buffer. Never blocks the analysis loop."""
        while not self._stop.is_set():
            cap = self.cap
            if cap is None:
                time.sleep(0.05)
                continue
            try:
                ok, raw = cap.read()
            except Exception as e:
                log.warning(f"cap.read raised {e!r}; will recover")
                ok, raw = False, None

            if not ok or raw is None:
                self._consecutive_errors += 1
                # Watchdog: reopen after repeated failures OR if nothing has
                # arrived for watchdog_timeout_s seconds.
                stale_for = time.time() - self._last_frame_ts
                if self._consecutive_errors >= 30 or stale_for > self._watchdog_timeout_s:
                    log.warning(
                        f"camera stalled (errors={self._consecutive_errors} stale={stale_for:.1f}s) "
                        f"— reopening {self.device}"
                    )
                    self._reopen_safe()
                else:
                    time.sleep(0.02)
                continue

            try:
                if self.decoder == "dual_yuyv":
                    visual, thermal = self._split_dual_yuyv(raw)
                else:
                    visual, thermal = self._visual_only(raw)
            except Exception as e:
                log.warning(f"decode failed: {e!r}")
                self._consecutive_errors += 1
                continue

            self._consecutive_errors = 0
            now = time.time()
            with self._lock:
                self._latest = (visual, thermal)
                self._latest_seq += 1
                self._last_frame_ts = now

    def _reopen_safe(self) -> None:
        try:
            if self.cap is not None:
                self.cap.release()
        except Exception:
            pass
        self.cap = None
        # Back off a bit so the kernel can release the device node
        time.sleep(0.5)
        try:
            self._open_device()
            self._last_frame_ts = time.time()
            self._reopens += 1
            log.info(f"camera reopened (count={self._reopens})")
        except Exception as e:
            log.warning(f"reopen failed: {e!r}; retrying in 1s")
            time.sleep(1.0)

    def read(self):
        """Return the latest (visual, thermal) pair without ever blocking on
        V4L2. Returns (None, None) only while we're still warming up / recovering.
        """
        with self._lock:
            latest = self._latest
            seq = self._latest_seq
        if latest is None:
            return None, None
        # Note: we do NOT bump _consumer_seq here — callers that want to know
        # whether they've seen this frame already can use `latest_seq()`.
        self._consumer_seq = seq
        return latest

    def latest_seq(self) -> int:
        """Sequence number of the most recently decoded frame (for dedup)."""
        with self._lock:
            return self._latest_seq

    def stats(self) -> dict:
        with self._lock:
            last_ts = self._last_frame_ts
            seq = self._latest_seq
        return {
            "seq": seq,
            "last_frame_age_s": round(time.time() - last_ts, 3) if last_ts else None,
            "reopens": self._reopens,
            "consecutive_errors": self._consecutive_errors,
        }

    def close(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
