"""Best-effort camera auto-detection.

Walks /sys/class/video4linux and matches USB VID:PID so we always grab the
thermal core even if something else is plugged in first and takes /dev/video0.
"""

from __future__ import annotations

import glob
import logging
import os
import re

log = logging.getLogger("camera-detect")


def _read(path: str) -> str | None:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return None


def _usb_ids_for(video_node: str) -> tuple[str | None, str | None]:
    # /sys/class/video4linux/video0 -> ../../devices/.../usbN/...../video4linux/video0
    sys_path = f"/sys/class/video4linux/{os.path.basename(video_node)}"
    if not os.path.exists(sys_path):
        return None, None
    real = os.path.realpath(sys_path)
    # Walk up until we find `idVendor`
    cur = real
    for _ in range(8):
        vend = os.path.join(cur, "idVendor")
        prod = os.path.join(cur, "idProduct")
        if os.path.exists(vend) and os.path.exists(prod):
            return _read(vend), _read(prod)
        cur = os.path.dirname(cur)
        if cur == "/":
            break
    return None, None


def autodetect(vid_pid: str, fallback: str = "/dev/video0") -> str:
    """Return the /dev/videoN path whose USB VID:PID matches `vid_pid`."""
    m = re.match(r"^\s*([0-9a-fA-F]{4})\s*:\s*([0-9a-fA-F]{4})\s*$", vid_pid or "")
    if not m:
        return fallback
    want_vid, want_pid = m.group(1).lower(), m.group(2).lower()

    candidates = sorted(glob.glob("/dev/video*"))
    for node in candidates:
        vid, pid = _usb_ids_for(node)
        if vid and pid and vid.lower() == want_vid and pid.lower() == want_pid:
            log.info(f"autodetect: matched {node}  VID:PID {vid}:{pid}")
            return node
    log.info(f"autodetect: no {vid_pid} match among {candidates}; using fallback {fallback}")
    return fallback
