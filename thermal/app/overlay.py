"""Overlay drawing (ROIs, min/max markers, temp scale, FPS, labels)."""

from __future__ import annotations

import cv2
import numpy as np


_FONT = cv2.FONT_HERSHEY_SIMPLEX


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

    # FPS counter (top-left)
    if overlay_cfg.get("fps_counter"):
        cv2.putText(out, f"{fps_actual:.0f} fps",
                    (6, 14), _FONT, 0.45, (255, 255, 255), 1, cv2.LINE_AA)

    return out


def render_colorbar(bar_h: int, palette_render_fn) -> np.ndarray:
    """Build a small vertical colorbar using the same palette as the live frame."""
    bar_w = 14
    # fake gradient 0..1
    ramp = np.linspace(1.0, 0.0, bar_h, dtype=np.float32).reshape(-1, 1)
    ramp = np.repeat(ramp, bar_w, axis=1)
    rendered, _, _ = palette_render_fn(ramp)
    return rendered
