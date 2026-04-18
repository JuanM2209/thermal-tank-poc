"""Overlay drawing (ROIs, min/max markers, temp scale, FPS, labels, timestamp)."""

from __future__ import annotations

from datetime import datetime

import cv2
import numpy as np


_FONT = cv2.FONT_HERSHEY_SIMPLEX
_MONO = cv2.FONT_HERSHEY_DUPLEX


def _draw_timestamp_badge(img, *, x: int = 8, y: int = 8) -> None:
    """Burn a date+time badge into the top-left corner (mutates `img`)."""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M:%S")

    # Scale font to frame size so it reads cleanly at 512x384 (default 2x upscale).
    H, W = img.shape[:2]
    fs = max(0.40, min(0.62, W / 900.0))
    th = 1

    (dw, dh), _ = cv2.getTextSize(date_str, _MONO, fs, th)
    (tw, tH), _ = cv2.getTextSize(time_str, _MONO, fs, th)
    pad_x, pad_y, gap = 8, 6, 4
    box_w = max(dw, tw) + pad_x * 2
    box_h = dh + tH + gap + pad_y * 2

    # Translucent dark background
    bg = img[y : y + box_h, x : x + box_w].copy()
    cv2.rectangle(bg, (0, 0), (box_w, box_h), (14, 14, 18), -1)
    cv2.addWeighted(bg, 0.72, img[y : y + box_h, x : x + box_w], 0.28, 0,
                    img[y : y + box_h, x : x + box_w])
    # Left accent bar (blue)
    cv2.rectangle(img, (x, y), (x + 3, y + box_h), (220, 140, 40), -1)
    # Outline
    cv2.rectangle(img, (x, y), (x + box_w, y + box_h), (60, 60, 70), 1)

    # Text (date dimmer, time brighter)
    date_y = y + pad_y + dh
    time_y = date_y + gap + tH
    cv2.putText(img, date_str, (x + pad_x, date_y),
                _MONO, fs, (185, 185, 195), th, cv2.LINE_AA)
    cv2.putText(img, time_str, (x + pad_x, time_y),
                _MONO, fs, (255, 255, 255), th, cv2.LINE_AA)


def _fmt_temp(t: float, unit: str = "C") -> str:
    if unit.upper() == "F":
        t = t * 9.0 / 5.0 + 32.0
        return f"{t:.1f}F"
    return f"{t:.1f}C"


def draw_frame_overlay(img, *, tanks, results, tmin, tmax, hot, cold,
                       overlay_cfg, fps_actual, temp_unit="C", upscale=1):
    """Paint ROIs, level lines, min/max markers, temp scale, FPS on a BGR frame.

    img:        HxWx3 uint8 (sensor-resolution palette frame)
    tanks:      list of {id, name, roi:{x,y,w,h}}
    results:    list of analyzer results (matched by id) or []
    tmin,tmax:  scalar min/max temp in °C over the current frame
    hot,cold:   (x, y, °C) pixel locations
    overlay_cfg: dict from config.stream.overlay
    upscale:    int multiplier applied last so text size is right
    """
    out = img.copy()
    res_by_id = {r["id"]: r for r in (results or [])}
    H, W = out.shape[:2]

    # Grid (light guide lines)
    if overlay_cfg.get("grid"):
        for gx in range(0, W, max(16, W // 8)):
            cv2.line(out, (gx, 0), (gx, H), (60, 60, 60), 1)
        for gy in range(0, H, max(16, H // 8)):
            cv2.line(out, (0, gy), (W, gy), (60, 60, 60), 1)

    # ROI boxes + level line + label
    if overlay_cfg.get("roi_boxes"):
        for t in tanks:
            r = t["roi"]
            res = res_by_id.get(t["id"])
            # colour by confidence
            color = (0, 255, 0)
            if res is None:
                color = (128, 128, 128)
            elif res.get("confidence") != "high":
                color = (0, 165, 255)
            cv2.rectangle(out, (r["x"], r["y"]),
                          (r["x"] + r["w"], r["y"] + r["h"]), color, 1)
            if res is not None and overlay_cfg.get("level_line", True):
                iy = r["y"] + int(res["interface_row"])
                cv2.line(out, (r["x"], iy), (r["x"] + r["w"], iy), (0, 0, 255), 1)
            if overlay_cfg.get("tank_labels", True) and res is not None:
                label = f"{t['id']} {res['level_pct']:.0f}%"
                cv2.putText(out, label, (r["x"], max(9, r["y"] - 3)),
                            _FONT, 0.35, color, 1, cv2.LINE_AA)

    # Centre crosshair
    if overlay_cfg.get("center_crosshair"):
        cx, cy = W // 2, H // 2
        cv2.line(out, (cx - 6, cy), (cx + 6, cy), (255, 255, 255), 1)
        cv2.line(out, (cx, cy - 6), (cx, cy + 6), (255, 255, 255), 1)

    # Min / max markers
    if overlay_cfg.get("max_marker") and hot is not None:
        hx, hy, ht = hot
        cv2.drawMarker(out, (hx, hy), (0, 0, 255), cv2.MARKER_CROSS, 8, 1)
        cv2.putText(out, _fmt_temp(ht, temp_unit), (hx + 5, hy - 3),
                    _FONT, 0.35, (0, 0, 255), 1, cv2.LINE_AA)
    if overlay_cfg.get("min_marker") and cold is not None:
        cx_, cy_, ct = cold
        cv2.drawMarker(out, (cx_, cy_), (255, 200, 0), cv2.MARKER_CROSS, 8, 1)
        cv2.putText(out, _fmt_temp(ct, temp_unit), (cx_ + 5, cy_ + 10),
                    _FONT, 0.35, (255, 200, 0), 1, cv2.LINE_AA)

    # Upscale BEFORE the temp scale + FPS text so they stay crisp
    if upscale and upscale > 1:
        out = cv2.resize(out, (W * upscale, H * upscale),
                         interpolation=cv2.INTER_NEAREST)
        H, W = out.shape[:2]

    # Temp scale (colorbar on the right edge)
    if overlay_cfg.get("temp_scale"):
        bar_w = 14
        bar_h = min(H - 60, 220)
        bar_x = W - bar_w - 8
        bar_y = (H - bar_h) // 2
        # solid translucent background
        cv2.rectangle(out, (bar_x - 52, bar_y - 16),
                      (bar_x + bar_w + 4, bar_y + bar_h + 16),
                      (0, 0, 0), -1)
        # labels
        cv2.putText(out, _fmt_temp(tmax, temp_unit),
                    (bar_x - 50, bar_y + 8), _FONT, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(out, _fmt_temp(tmin, temp_unit),
                    (bar_x - 50, bar_y + bar_h + 2), _FONT, 0.4,
                    (255, 255, 255), 1, cv2.LINE_AA)

    # Timestamp badge (top-left) — burned in so it's visible in recordings, snapshots, MJPEG
    if overlay_cfg.get("timestamp", True):
        _draw_timestamp_badge(out, x=8, y=8)

    # FPS counter (bottom-left so it doesn't fight the timestamp)
    if overlay_cfg.get("fps_counter"):
        cv2.putText(out, f"{fps_actual:.0f} fps",
                    (8, H - 8), _FONT, 0.45, (200, 200, 200), 1, cv2.LINE_AA)

    return out


def render_colorbar(bar_h: int, palette_render_fn) -> np.ndarray:
    """Build a small vertical colorbar using the same palette as the live frame."""
    bar_w = 14
    # fake gradient 0..1
    ramp = np.linspace(1.0, 0.0, bar_h, dtype=np.float32).reshape(-1, 1)
    ramp = np.repeat(ramp, bar_w, axis=1)
    rendered, _, _ = palette_render_fn(ramp)
    return rendered
