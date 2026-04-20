"""Overlay drawing (ROIs, min/max markers, temp scale, FPS, labels, timestamp)."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import cv2
import numpy as np


_FONT = cv2.FONT_HERSHEY_SIMPLEX
_MONO = cv2.FONT_HERSHEY_DUPLEX


def _resolve_tz(tz_name: str | None):
    if not tz_name:
        return None
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError:
        return None


def _draw_corner_badge(img, fps_actual: float | None, tz_name: str | None = None) -> None:
    """Burn a compact date+time+fps badge into the bottom-right corner."""
    tz = _resolve_tz(tz_name)
    now = datetime.now(tz) if tz else datetime.now().astimezone()
    stamp = now.strftime("%Y-%m-%d %H:%M:%S %Z").rstrip()
    fps_str = f"{fps_actual:.0f} fps" if fps_actual is not None else ""

    H, W = img.shape[:2]
    fs = max(0.32, min(0.44, W / 1400.0))
    th = 1

    parts = [stamp]
    if fps_str:
        parts.append(fps_str)
    text = "  ".join(parts)

    (tw, th_px), _ = cv2.getTextSize(text, _MONO, fs, th)
    pad_x, pad_y = 6, 4
    box_w = tw + pad_x * 2
    box_h = th_px + pad_y * 2

    x = W - box_w - 8
    y = H - box_h - 8
    if x < 0 or y < 0:
        return

    bg = img[y : y + box_h, x : x + box_w].copy()
    cv2.rectangle(bg, (0, 0), (box_w, box_h), (14, 14, 18), -1)
    cv2.addWeighted(bg, 0.72, img[y : y + box_h, x : x + box_w], 0.28, 0,
                    img[y : y + box_h, x : x + box_w])
    cv2.rectangle(img, (x, y), (x + 2, y + box_h), (220, 140, 40), -1)
    cv2.rectangle(img, (x, y), (x + box_w, y + box_h), (60, 60, 70), 1)

    cv2.putText(img, text, (x + pad_x, y + pad_y + th_px - 1),
                _MONO, fs, (235, 235, 240), th, cv2.LINE_AA)


def _fmt_temp(t: float, unit: str = "C") -> str:
    if unit.upper() == "F":
        t = t * 9.0 / 5.0 + 32.0
        return f"{t:.1f}F"
    return f"{t:.1f}C"


def _tank_label_lines(tank: dict, res: dict | None) -> list[str]:
    """Build the stacked label lines drawn above a tank ROI.

    v1.12: the operator asked for the detail block to live OUTSIDE the
    ROI so the thermal image inside the box stays clean. We emit up to
    three lines: ``LEVEL 80 %`` + ``10.86 FT`` + ``154 BBL`` when a
    ``reading`` is present, and fall back to a single compact line when
    the tank has no geometry or the reading is suppressed.
    """
    tid = tank.get("id", "?")
    if res is None:
        return [tid]
    reliability = res.get("reliability")
    if reliability == "uniform":
        return [f"{tid} UNIFORM"]
    if reliability == "uncertain":
        return [f"{tid} UNCERTAIN"]
    lvl = res.get("level_pct")
    if lvl is None:
        return [f"{tid} --"]
    lines = [f"{tid} LVL {lvl:.0f}%"]
    reading = res.get("reading") or {}
    ft = reading.get("level_ft")
    bbl = reading.get("volume_bbl")
    if ft is not None:
        lines.append(f"{float(ft):.2f} FT")
    if bbl is not None:
        lines.append(f"{int(round(float(bbl)))} BBL")
    return lines


def _draw_tank_label_stack(
    img,
    x: int,
    y_top_of_roi: int,
    lines: list[str],
    color: tuple[int, int, int],
    fs: float = 0.35,
) -> None:
    """Draw a vertical stack of label lines above the ROI top edge.

    Lines are right-side up (top-most line is furthest from the ROI),
    so the operator reads top-to-bottom as: level %, height, volume.
    Falls back to drawing the primary line only if there is no room
    above the ROI for the full stack.
    """
    if not lines:
        return
    H = img.shape[0]
    th = 1
    # Measure line height from the first line; cv2.putText uses baseline
    # anchoring so we add a small padding between lines.
    (_, line_h), _ = cv2.getTextSize(lines[0], _FONT, fs, th)
    pad = 2
    total_h = (line_h + pad) * len(lines)
    start_y = y_top_of_roi - pad  # baseline of the LAST (closest-to-ROI) line
    if start_y - total_h < 0:
        # Not enough room above ROI — drop to a single compact line
        # drawn where v1.11 drew it.
        cv2.putText(
            img, lines[0], (x, max(9, y_top_of_roi - 3)),
            _FONT, fs, color, th, cv2.LINE_AA,
        )
        return
    # lines are emitted top-to-bottom in the list; draw the LAST element
    # immediately above the ROI and the FIRST element at the top.
    for i, text in enumerate(reversed(lines)):
        baseline_y = start_y - i * (line_h + pad)
        cv2.putText(img, text, (x, baseline_y), _FONT, fs, color, th, cv2.LINE_AA)


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
            # v1.11: colour by reliability first (uniform = neutral grey,
            # uncertain = amber), then by legacy confidence for backward
            # compat with older results payloads.
            color = (0, 255, 0)
            if res is None:
                color = (128, 128, 128)
            elif res.get("reliability") == "uniform":
                color = (148, 163, 184)     # slate — "can't tell"
            elif res.get("reliability") == "uncertain":
                color = (250, 204, 21)      # amber — "held at last good"
            elif res.get("confidence") != "high":
                color = (0, 165, 255)
            cv2.rectangle(out, (r["x"], r["y"]),
                          (r["x"] + r["w"], r["y"] + r["h"]), color, 1)
            # Only draw the level line when we actually have a level. A
            # uniform ROI has no meaningful interface to paint.
            if (res is not None
                and res.get("level_pct") is not None
                and overlay_cfg.get("level_line", True)):
                iy = r["y"] + int(res["interface_row"])
                cv2.line(out, (r["x"], iy), (r["x"] + r["w"], iy), (0, 0, 255), 1)
            if overlay_cfg.get("tank_labels", True):
                # v1.12 — render the detail block OUTSIDE the ROI in a
                # multi-line stack so the thermal image stays clean.
                lines = _tank_label_lines(t, res)
                _draw_tank_label_stack(out, r["x"], r["y"], lines, color)

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

    # Compact badge (bottom-right): timestamp + FPS merged.
    show_ts = overlay_cfg.get("timestamp", True)
    show_fps = overlay_cfg.get("fps_counter", True)
    if show_ts or show_fps:
        _draw_corner_badge(
            out,
            fps_actual if show_fps else None,
            tz_name=overlay_cfg.get("display_tz") if show_ts else None,
        )

    return out


def render_colorbar(bar_h: int, palette_render_fn) -> np.ndarray:
    """Build a small vertical colorbar using the same palette as the live frame."""
    bar_w = 14
    # fake gradient 0..1
    ramp = np.linspace(1.0, 0.0, bar_h, dtype=np.float32).reshape(-1, 1)
    ramp = np.repeat(ramp, bar_w, axis=1)
    rendered, _, _ = palette_render_fn(ramp)
    return rendered
