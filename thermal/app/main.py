"""Thermal tank level detection — main orchestrator.

Pipeline per frame:
    capture -> (visual BGR, thermal °C)
    palette.render(thermal) -> palette-rendered BGR + (tmin, tmax)
    palette.find_hot_cold(thermal) -> hot, cold markers
    overlay.draw(...) -> rendered frame with ROI boxes, markers, FPS, scale
    analyzer.analyze(thermal) -> per-tank levels (publish when interval elapsed)
    state.publish(...) -> latest frame snapshot for the web API
    event detector -> level_change / low_confidence / camera_lost
"""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
from collections import deque

import yaml

from analyzer import TankAnalyzer
from camera_detect import autodetect
from capture import ThermalCapture
from overlay import draw_frame_overlay
from palette import (
    apply_isotherm,
    blend_with_visual,
    find_hot_cold,
    render,
    transform,
)
from publisher import HttpPublisher
from recorder import Recorder
from state import PERF, SHARED
from stream import WebServer

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")


DEFAULT_CONFIG = "/app/config.yaml"
RUNTIME_OVERRIDE = "/app/data/runtime.json"   # volume-mounted, survives restarts


def _deep_merge(base: dict, patch: dict) -> dict:
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # Apply persisted runtime overrides (from the web UI) if present
    if os.path.exists(RUNTIME_OVERRIDE):
        try:
            with open(RUNTIME_OVERRIDE, "r", encoding="utf-8") as f:
                overrides = json.load(f)
            _deep_merge(cfg, overrides)
            log.info(f"Runtime overrides merged from {RUNTIME_OVERRIDE}")
        except Exception as e:
            log.warning(f"Ignoring malformed runtime override: {e}")
    return cfg


def open_camera(cam_cfg: dict) -> ThermalCapture:
    device = cam_cfg.get("device", "/dev/video0")
    if cam_cfg.get("autodetect") and cam_cfg.get("vid_pid"):
        device = autodetect(cam_cfg["vid_pid"], fallback=device)
    cap = ThermalCapture(
        device=device,
        width=cam_cfg.get("width", 256),
        height=cam_cfg.get("height", 384),
        fps=cam_cfg.get("fps", 25),
        decoder=cam_cfg.get("decoder", "dual_yuyv"),
        kelvin_divisor=cam_cfg.get("kelvin_divisor", 64.0),
    )
    cap.open()
    return cap


class EventDetector:
    """Emit level_change / low_confidence events without spamming."""
    def __init__(self, min_level_delta: float = 5.0):
        self.min_level_delta = min_level_delta
        self._last_level: dict[str, float] = {}
        self._last_conf:  dict[str, str] = {}

    def scan(self, results):
        for r in results:
            prev = self._last_level.get(r["id"])
            if prev is None or abs(prev - r["level_pct"]) >= self.min_level_delta:
                SHARED.append_event("level_change", id=r["id"],
                                    level_pct=r["level_pct"], prev=prev)
                self._last_level[r["id"]] = r["level_pct"]
            prev_c = self._last_conf.get(r["id"])
            if prev_c != r["confidence"]:
                if r["confidence"] == "low":
                    SHARED.append_event("low_confidence", id=r["id"],
                                        gradient_peak=r["gradient_peak"])
                self._last_conf[r["id"]] = r["confidence"]


def main():
    cfg_path = os.environ.get("CONFIG", DEFAULT_CONFIG)
    cfg = load_config(cfg_path)
    log.info(f"Config loaded: {cfg_path}")

    # ------ camera ------
    cap = open_camera(cfg["camera"])

    # ------ analyzer ------
    analyzer = TankAnalyzer(
        cfg.get("tanks", []),
        smoothing=cfg["analysis"].get("smoothing_window", 7),
        method=cfg["analysis"].get("gradient_method", "sobel"),
        invert_level=cfg["analysis"].get("invert_level", False),
    )

    # ------ publisher (HTTP -> Node-RED) ------
    pub_cfg = cfg.get("publisher", {})
    endpoint = os.environ.get("PUBLISH_ENDPOINT", pub_cfg.get("endpoint"))
    site_id = os.environ.get("SITE_ID") or cfg.get("site", {}).get("id") or "unknown"
    publisher = (
        HttpPublisher(endpoint, timeout=pub_cfg.get("timeout", 3.0), site_id=site_id)
        if endpoint
        else None
    )
    if not publisher:
        log.warning("No publisher.endpoint configured — running stream-only")

    # ------ web server ------
    os.makedirs(os.path.dirname(RUNTIME_OVERRIDE), exist_ok=True) if os.path.isdir(os.path.dirname(RUNTIME_OVERRIDE)) else None

    # When config is mutated via the web API, rebuild the analyzer and persist.
    reload_flag = {"v": 0}
    def _on_cfg_change():
        reload_flag["v"] += 1

    recorder = Recorder(
        snapshot_dir=cfg.get("stream", {}).get("snapshot_dir", "/app/data/snapshots"),
        recording_dir=cfg.get("stream", {}).get("recording_dir", "/app/data/recordings"),
    )
    server = WebServer(
        config=cfg,
        on_config_change=_on_cfg_change,
        persist_path=RUNTIME_OVERRIDE if os.path.isdir(os.path.dirname(RUNTIME_OVERRIDE)) else None,
        recorder=recorder,
        publisher=publisher,
    )
    if cfg.get("stream", {}).get("enabled", True):
        server.run_threaded(port=cfg["stream"].get("port", 8080))

    # ------ loop state ------
    interval = cfg["analysis"].get("interval_seconds", 2)
    running = {"v": True}
    def _stop(signo, _frame):
        log.info(f"Received signal {signo}, stopping...")
        running["v"] = False
    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    last_publish = 0.0
    frame_count = 0
    fps_window = deque(maxlen=30)
    last_tick = time.time()
    local_reload_seen = 0
    last_seen_seq = -1
    event_det = EventDetector(min_level_delta=cfg["analysis"].get("level_event_delta", 5.0))
    # Pipeline stride — process 1 of every N camera frames. On the i.MX6 the
    # 25 fps pipeline saturates the CPU; stride=3 brings us to ~8 fps, freeing
    # enough core to stay stable over long runs. Tank levels change over
    # seconds, so downsampling here is visually invisible.
    pipeline_stride = max(1, int(cfg["analysis"].get("pipeline_stride", 1)))
    open("/tmp/alive", "w").close()

    # Rolling per-stage latency budget (ms). Logged every 50 frames so we can
    # see exactly which stage regresses when the scene changes.
    stage_ms = {"wait": 0.0, "analyze": 0.0, "render": 0.0, "overlay": 0.0, "publish": 0.0, "share": 0.0}

    frozen_thermal = None
    frozen_visual = None

    while running["v"]:
        try:
            # Wait for a *new* frame from the background capture thread,
            # instead of driving capture synchronously on this thread.
            # With pipeline_stride=N we only accept every Nth new seq,
            # which throttles CPU-bound pipeline stages without losing
            # the latest camera frame.
            t_wait_start = time.perf_counter()
            visual_raw = thermal_raw = None
            target_seq = last_seen_seq + pipeline_stride if last_seen_seq >= 0 else -1
            while running["v"]:
                seq = cap.latest_seq()
                if seq > target_seq:
                    visual_raw, thermal_raw = cap.read()
                    if thermal_raw is not None:
                        last_seen_seq = seq
                        break
                time.sleep(0.01)
            if thermal_raw is None:
                continue
            stage_ms["wait"] += (time.perf_counter() - t_wait_start) * 1000.0
            frame_count += 1

            # ---- live config (possibly just mutated via HTTP) ----
            if reload_flag["v"] != local_reload_seen:
                cfg = server.cfg()
                analyzer = TankAnalyzer(
                    cfg.get("tanks", []),
                    smoothing=cfg["analysis"].get("smoothing_window", 7),
                    method=cfg["analysis"].get("gradient_method", "sobel"),
                    invert_level=cfg["analysis"].get("invert_level", False),
                )
                local_reload_seen = reload_flag["v"]
                log.info(f"Config reloaded v={local_reload_seen}")

            stream_cfg = cfg.get("stream", {})

            # ---- freeze ----
            if stream_cfg.get("freeze"):
                if frozen_thermal is None:
                    frozen_thermal = thermal_raw.copy()
                    frozen_visual = visual_raw.copy() if visual_raw is not None else None
                thermal = frozen_thermal
                visual = frozen_visual
            else:
                frozen_thermal = frozen_visual = None
                thermal = thermal_raw
                visual = visual_raw

            # ---- rotation + flip (BEFORE analysis so ROIs match the displayed frame) ----
            rot = int(stream_cfg.get("rotate", 0) or 0)
            flip_h = bool(stream_cfg.get("flip_h", False))
            flip_v = bool(stream_cfg.get("flip_v", False))
            if rot or flip_h or flip_v:
                thermal = transform(thermal, rot, flip_h, flip_v)
                if visual is not None:
                    visual = transform(visual, rot, flip_h, flip_v)

            # ---- analyze ----
            t0 = time.perf_counter()
            results = analyzer.analyze(thermal)
            stage_ms["analyze"] += (time.perf_counter() - t0) * 1000.0

            # ---- palette render (optionally pinned range) ----
            t0 = time.perf_counter()
            palette_name = stream_cfg.get("palette", "iron")
            source = stream_cfg.get("source", "thermal")
            rmin = stream_cfg.get("range_min")
            rmax = stream_cfg.get("range_max")
            if source == "visual" and visual is not None:
                rendered, tmin, tmax = visual.copy(), float(thermal.min()), float(thermal.max())
            else:
                rendered, tmin, tmax = render(thermal, palette_name, rmin, rmax)
                if source == "blend" and visual is not None:
                    rendered = blend_with_visual(visual, rendered, alpha=0.55)

            # ---- isotherm highlight ----
            if stream_cfg.get("isotherm_enabled"):
                ic = stream_cfg.get("isotherm_color", [255, 255, 255])
                color = (int(ic[0]), int(ic[1]), int(ic[2]))
                rendered = apply_isotherm(
                    rendered, thermal,
                    float(stream_cfg.get("isotherm_min", 35.0)),
                    float(stream_cfg.get("isotherm_max", 60.0)),
                    color,
                )

            hot, cold = find_hot_cold(thermal)
            stage_ms["render"] += (time.perf_counter() - t0) * 1000.0

            # ---- overlay ----
            t0 = time.perf_counter()
            fps_now = 0.0
            if len(fps_window) > 1:
                fps_now = (len(fps_window) - 1) / max(1e-3, fps_window[-1] - fps_window[0])
            fps_window.append(time.time())

            upscale = int(stream_cfg.get("upscale", 2))
            rendered = draw_frame_overlay(
                rendered,
                tanks=cfg.get("tanks", []),
                results=results,
                tmin=tmin, tmax=tmax,
                hot=hot, cold=cold,
                overlay_cfg=stream_cfg.get("overlay", {}),
                fps_actual=fps_now,
                temp_unit=cfg.get("ui", {}).get("temp_unit", "C"),
                upscale=upscale,
            )
            stage_ms["overlay"] += (time.perf_counter() - t0) * 1000.0

            # ---- publish to Node-RED ----
            t0 = time.perf_counter()
            now = time.time()
            only_hi = cfg.get("analysis", {}).get("publish_only_high_confidence", False)
            if results and (now - last_publish) >= interval:
                pub_results = (
                    [r for r in results if r["confidence"] == "high"]
                    if only_hi
                    else results
                )
                if publisher and pub_results:
                    publisher.publish(pub_results, calibration=cfg.get("calibration"))
                last_publish = now

            # ---- events ----
            event_det.scan(results)
            stage_ms["publish"] += (time.perf_counter() - t0) * 1000.0

            # ---- share with web layer ----
            t0 = time.perf_counter()
            SHARED.publish(
                thermal=thermal, visual=visual, rendered=rendered,
                rendered_upscale=upscale,
                tmin=tmin, tmax=tmax,
                hot=hot, cold=cold,
                results=results, fps=fps_now, frame_idx=frame_count,
            )

            # ---- video recording ----
            if recorder.recording:
                recorder.write(rendered)
            stage_ms["share"] += (time.perf_counter() - t0) * 1000.0

            if frame_count % 50 == 0:
                os.utime("/tmp/alive", None)
                avg = {k: v / 50.0 for k, v in stage_ms.items()}
                cap_stats = cap.stats()
                reader_stats = cap.reader_stats()
                log.info(
                    f"frame#{frame_count} fps={fps_now:.1f} tanks={len(results)} "
                    f"tmin={tmin:.1f} tmax={tmax:.1f} "
                    f"stage_ms(avg)=wait:{avg['wait']:.1f} analyze:{avg['analyze']:.1f} "
                    f"render:{avg['render']:.1f} overlay:{avg['overlay']:.1f} "
                    f"publish:{avg['publish']:.1f} share:{avg['share']:.1f} "
                    f"reader(read:{reader_stats.get('avg_read_ms', 0):.1f} max:{reader_stats.get('max_read_ms', 0):.1f} decode:{reader_stats.get('avg_decode_ms', 0):.1f}) "
                    f"cap(seq={cap_stats['seq']} stale={cap_stats['last_frame_age_s']}s reopens={cap_stats['reopens']})"
                )
                PERF.record_window(
                    stage_ms_avg=avg,
                    fps=fps_now,
                    frame_idx=frame_count,
                    cap_stats=cap_stats,
                    reader_stats=reader_stats,
                )
                for k in stage_ms:
                    stage_ms[k] = 0.0

        except KeyboardInterrupt:
            break
        except Exception as e:
            log.exception(f"Loop error: {e}")
            time.sleep(1)

    log.info("Shutting down...")
    cap.close()
    if publisher:
        publisher.stop()
    sys.exit(0)


if __name__ == "__main__":
    main()
