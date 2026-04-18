"""
UVC capture for the Thermal Master P2 Pro (and similar Infiray/Xtherm cores).

The camera exposes a YUYV stream where the frame is 2x the sensor height:
  top half   = visual/pseudo-color image (YUYV)
  bottom half = raw thermal data (uint16 per pixel, little-endian)
  raw -> Celsius:  (raw / kelvin_divisor) - 273.15

If this layout does not match your unit, change `decoder` in config.yaml and
the format will be auto-probed at startup (see probe.py).
"""

import cv2
import numpy as np
import logging
import time

log = logging.getLogger("capture")


class ThermalCapture:
    def __init__(self, device="/dev/video0", width=256, height=384, fps=25,
                 decoder="dual_yuyv", kelvin_divisor=64.0):
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.decoder = decoder
        self.kdiv = float(kelvin_divisor)
        self.sensor_h = height // 2 if decoder == "dual_yuyv" else height
        self.cap = None

    def open(self):
        self.cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            raise RuntimeError(f"Cannot open {self.device}")

        fourcc = cv2.VideoWriter_fourcc('Y', 'U', 'Y', 'V')
        self.cap.set(cv2.CAP_PROP_FOURCC, fourcc)
        # Critical: disable automatic RGB conversion so we receive raw YUYV
        self.cap.set(cv2.CAP_PROP_CONVERT_RGB, 0)
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        self.cap.set(cv2.CAP_PROP_FPS, self.fps)

        aw = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        ah = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        log.info(f"Opened {self.device} requested {self.width}x{self.height}@{self.fps} -> got {aw}x{ah}")

        # Warm-up — some thermal cores drop the first few frames
        for _ in range(5):
            self.cap.read()
            time.sleep(0.05)

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

    def read(self):
        ok, raw = self.cap.read()
        if not ok or raw is None:
            return None, None
        if self.decoder == "dual_yuyv":
            return self._split_dual_yuyv(raw)
        return self._visual_only(raw)

    def close(self):
        if self.cap is not None:
            self.cap.release()
            self.cap = None
