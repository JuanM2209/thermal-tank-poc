"""MJPEG + JSON API server.

Routes
------
- GET  /                           SPA
- GET  /stream.mjpg                live palette+overlay stream (iframe-able)
- GET  /api/state                  latest readings
- GET  /api/temp?x=...&y=...       temperature at sensor pixel (C)
- GET  /api/line?x1=...&y1=...     line profile
- GET  /api/config                 merged config
- PATCH /api/config                deep-merge partial update
- GET  /api/tanks
- POST /api/tanks                  add a tank
- PATCH /api/tanks/<id>            update fields
- DELETE /api/tanks/<id>           remove
- POST /api/detect                 run OpenCV auto-detect
- POST /api/detect/accept          persist detected tanks
- POST /api/calibrate              10 s auto-calibration
- GET  /api/events?since=SEQ       event log
- POST /api/snapshot, record/start, record/stop, files, ...
- GET  /healthz
"""

from __future__ import annotations

import copy
import json
import logging
import os
import threading
import time
from typing import Callable

import cv2
import numpy as np
from flask import Flask, Response, abort, jsonify, request, send_file

import detect as detector
from calibration import as_config_patch, calibrate
from state import SHARED
from webui import INDEX_HTML

log = logging.getLogger("stream")

DEFAULT_IFRAME_ORIGINS = "https://*.datadesng.com"
CALIBRATION_FRAME_COUNT = 30
CALIBRATION_MAX_SECONDS = 12.0


class WebServer:
    def __init__(
        self,
        config: dict,
        on_config_change: Callable[[], None] | None = None,
        persist_path: str | None = None,
        recorder=None,
    ):
        self._cfg = config
        self._cfg_lock = threading.Lock()
        self._on_change = on_config_change or (lambda: None)
        self._persist_path = persist_path
        self._recorder = recorder
        self.app = Flask("thermal")
        self.app.config["JSON_SORT_KEYS"] = False
        self._install_headers()
        self._setup_routes()

    # ---------- Config helpers ----------
    def cfg(self) -> dict:
        with self._cfg_lock:
            return copy.deepcopy(self._cfg)

    def _deep_merge(self, base: dict, patch: dict) -> dict:
        for k, v in patch.items():
            if isinstance(v, dict) and isinstance(base.get(k), dict):
                self._deep_merge(base[k], v)
            else:
                base[k] = v
        return base

    def _persist(self) -> None:
        if not self._persist_path:
            return
        try:
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(self._cfg, f, indent=2)
        except Exception as e:
            log.warning(f"persist failed: {e}")

    def apply_patch(self, patch: dict) -> None:
        with self._cfg_lock:
            self._deep_merge(self._cfg, patch)
            self._persist()
        self._on_change()
        SHARED.bump_cfg()
        SHARED.append_event("config_change", keys=list(patch.keys()))

    # ---------- Iframe-friendly headers ----------
    def _install_headers(self) -> None:
        app = self.app

        @app.after_request
        def _headers(response: Response) -> Response:
            origins = (
                self.cfg().get("ui", {}).get("iframe_origins")
                or DEFAULT_IFRAME_ORIGINS
            )
            # Remove the Flask default deny and allow embedding from our subdomains.
            response.headers.pop("X-Frame-Options", None)
            response.headers["Content-Security-Policy"] = (
                f"frame-ancestors 'self' {origins}"
            )
            return response

    # ---------- Routes ----------
    def _setup_routes(self) -> None:
        app = self.app

        @app.route("/")
        def index():
            return INDEX_HTML

        @app.route("/healthz")
        def healthz():
            snap = SHARED.snapshot()
            return ("ok", 200) if snap.rendered is not None else ("no-frame", 503)

        @app.route("/stream.mjpg")
        def stream():
            resp = Response(
                self._mjpeg_gen(),
                mimetype="multipart/x-mixed-replace; boundary=frame",
            )
            # Soft anti-buffering only — don't override connection handling
            # or direct_passthrough (Flask auto-sets it for generators).
            resp.headers["X-Accel-Buffering"] = "no"
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            return resp

        @app.route("/api/state")
        def api_state():
            s = SHARED.snapshot()
            h = w = 0
            if s.rendered is not None:
                h, w = s.rendered.shape[:2]
            return jsonify({
                "ts": int(s.ts * 1000),   # milliseconds, single source of truth
                "frame_idx": s.frame_idx,
                "fps": round(s.fps, 2),
                "w": w, "h": h,
                "upscale": s.rendered_upscale,
                "tmin": round(s.tmin, 2),
                "tmax": round(s.tmax, 2),
                "hot":  None if s.hot  is None else {"x": s.hot[0],  "y": s.hot[1],  "t": round(s.hot[2],  2)},
                "cold": None if s.cold is None else {"x": s.cold[0], "y": s.cold[1], "t": round(s.cold[2], 2)},
                "results": s.results,
                "tanks": self.cfg().get("tanks", []),
                "calibration": self.cfg().get("calibration"),
            })

        @app.route("/api/temp")
        def api_temp():
            try:
                x = int(request.args["x"]); y = int(request.args["y"])
            except (KeyError, ValueError):
                abort(400)
            s = SHARED.snapshot()
            if s.thermal is None:
                return jsonify({"t": None, "err": "no-frame"}), 503
            H, W = s.thermal.shape
            if not (0 <= x < W and 0 <= y < H):
                return jsonify({"t": None, "err": "out-of-bounds", "w": W, "h": H}), 400
            x0, x1 = max(0, x - 1), min(W, x + 2)
            y0, y1 = max(0, y - 1), min(H, y + 2)
            patch = s.thermal[y0:y1, x0:x1]
            return jsonify({"t": round(float(np.median(patch)), 2), "x": x, "y": y})

        @app.route("/api/config", methods=["GET", "PATCH"])
        def api_config():
            if request.method == "GET":
                return jsonify(self.cfg())
            patch = request.get_json(silent=True) or {}
            if not isinstance(patch, dict):
                abort(400)
            self.apply_patch(patch)
            return jsonify(self.cfg())

        @app.route("/api/tanks", methods=["GET", "POST"])
        def api_tanks():
            if request.method == "GET":
                return jsonify(self.cfg().get("tanks", []))
            body = request.get_json(silent=True) or {}
            required = {"id", "roi"}
            if not required.issubset(body.keys()):
                return jsonify({"error": f"missing {required - set(body)}"}), 400
            tanks = self.cfg().get("tanks", [])
            if any(t.get("id") == body["id"] for t in tanks):
                return jsonify({"error": "duplicate id"}), 409
            new_tanks = tanks + [body]
            self.apply_patch({"tanks": new_tanks})
            SHARED.append_event("tank_added", id=body["id"])
            return jsonify(body), 201

        @app.route("/api/tanks/<tid>", methods=["PATCH", "DELETE"])
        def api_tank_one(tid):
            tanks = self.cfg().get("tanks", [])
            idx = next((i for i, t in enumerate(tanks) if t.get("id") == tid), -1)
            if idx < 0:
                return jsonify({"error": "not found"}), 404
            if request.method == "DELETE":
                new_tanks = [t for t in tanks if t.get("id") != tid]
                self.apply_patch({"tanks": new_tanks})
                SHARED.append_event("tank_removed", id=tid)
                return "", 204
            patch = request.get_json(silent=True) or {}
            new_tanks = copy.deepcopy(tanks)
            self._deep_merge(new_tanks[idx], patch)
            self.apply_patch({"tanks": new_tanks})
            return jsonify(new_tanks[idx])

        @app.route("/api/events")
        def api_events():
            try:
                since = int(request.args.get("since", "0"))
            except ValueError:
                since = 0
            return jsonify(SHARED.events_since(since))

        # ---- auto-detect ----
        @app.route("/api/detect", methods=["POST"])
        def api_detect():
            body = request.get_json(silent=True) or {}
            n = int(body.get("max", 4))
            frames = self._sample_thermal_frames(
                count=int(body.get("samples", 20)),
                timeout_s=float(body.get("timeout_s", 6.0)),
            )
            if not frames:
                return jsonify({"error": "no-frame"}), 503
            candidates = detector.detect(
                frames[-1], max_candidates=n, frames=frames,
            )
            SHARED.append_event("auto_detect", count=len(candidates))
            return jsonify({"candidates": candidates, "frames_used": len(frames)})

        @app.route("/api/detect/accept", methods=["POST"])
        def api_detect_accept():
            body = request.get_json(silent=True) or {}
            tanks = body.get("tanks") or []
            if not isinstance(tanks, list):
                abort(400)
            self.apply_patch({"tanks": tanks})
            return jsonify({"ok": True, "count": len(tanks)})

        # ---- auto-calibration ----
        @app.route("/api/calibrate", methods=["POST"])
        def api_calibrate():
            body = request.get_json(silent=True) or {}
            frames = self._sample_thermal_frames(
                count=int(body.get("samples", CALIBRATION_FRAME_COUNT)),
                timeout_s=float(body.get("timeout_s", CALIBRATION_MAX_SECONDS)),
            )
            if not frames:
                return jsonify({"error": "no-frame"}), 503
            tanks = self.cfg().get("tanks", [])
            rois = [t["roi"] for t in tanks if "roi" in t]
            mediums = [t.get("medium", "unknown") for t in tanks]
            result = calibrate(frames, rois, mediums)
            self.apply_patch(as_config_patch(result))
            SHARED.append_event(
                "calibrated",
                medium=result.medium_dominant,
                locked=result.range_locked,
                delta=result.thermal_delta_c,
            )
            return jsonify({
                "ok": True,
                "frames_used": len(frames),
                "calibration": {
                    "emissivity": result.emissivity,
                    "reflect_temp_c": result.reflect_temp_c,
                    "range_min_c": result.range_min_c,
                    "range_max_c": result.range_max_c,
                    "range_locked": result.range_locked,
                    "calibrated_at": result.calibrated_at,
                    "notes": result.notes,
                    "medium_dominant": result.medium_dominant,
                    "thermal_delta_c": result.thermal_delta_c,
                },
            })

        @app.route("/api/measure", methods=["POST"])
        def api_measure():
            """Shape-based temperature query.

            Body: {shape: "point"|"line"|"box"|"polygon", coords: [...], coord_space: "rendered"|"sensor"}
              point   coords: [[x, y]]
              line    coords: [[x1, y1], [x2, y2]]
              box     coords: [[x1, y1], [x2, y2]]  (two corners)
              polygon coords: [[x, y], [x, y], ...] (>= 3 points)
            Coordinates default to rendered-frame space (what the client canvas sees)
            and are automatically downscaled to sensor-space.
            """
            body = request.get_json(silent=True) or {}
            shape = str(body.get("shape", "point")).lower()
            coords = body.get("coords") or []
            if not isinstance(coords, list) or not coords:
                return jsonify({"err": "bad-coords"}), 400

            s = SHARED.snapshot()
            if s.thermal is None:
                return jsonify({"err": "no-frame"}), 503
            H, W = s.thermal.shape
            upscale = max(1, int(s.rendered_upscale or 1))
            space = str(body.get("coord_space", "rendered")).lower()
            scale = 1.0 / upscale if space == "rendered" else 1.0

            def _pt(xy):
                x = int(round(float(xy[0]) * scale))
                y = int(round(float(xy[1]) * scale))
                return max(0, min(W - 1, x)), max(0, min(H - 1, y))

            try:
                if shape == "point":
                    x, y = _pt(coords[0])
                    x0, x1 = max(0, x - 1), min(W, x + 2)
                    y0, y1 = max(0, y - 1), min(H, y + 2)
                    vals = s.thermal[y0:y1, x0:x1].flatten()
                elif shape == "line":
                    if len(coords) < 2:
                        return jsonify({"err": "need 2 points"}), 400
                    x1, y1 = _pt(coords[0])
                    x2, y2 = _pt(coords[1])
                    length = max(1, int(np.hypot(x2 - x1, y2 - y1)))
                    xs = np.linspace(x1, x2, length).astype(int)
                    ys = np.linspace(y1, y2, length).astype(int)
                    vals = s.thermal[ys, xs]
                elif shape == "box":
                    if len(coords) < 2:
                        return jsonify({"err": "need 2 corners"}), 400
                    x1, y1 = _pt(coords[0])
                    x2, y2 = _pt(coords[1])
                    xmin, xmax = sorted((x1, x2))
                    ymin, ymax = sorted((y1, y2))
                    vals = s.thermal[ymin:ymax + 1, xmin:xmax + 1].flatten()
                elif shape == "polygon":
                    if len(coords) < 3:
                        return jsonify({"err": "need >= 3 points"}), 400
                    pts = np.array([_pt(p) for p in coords], dtype=np.int32)
                    mask = np.zeros((H, W), dtype=np.uint8)
                    cv2.fillPoly(mask, [pts], 1)
                    vals = s.thermal[mask.astype(bool)]
                else:
                    return jsonify({"err": f"bad shape: {shape}"}), 400
            except Exception as e:
                return jsonify({"err": f"measure failed: {e}"}), 500

            if vals is None or len(vals) == 0:
                return jsonify({"err": "empty"}), 400

            vals = np.asarray(vals, dtype=np.float32)
            return jsonify({
                "shape": shape,
                "min": round(float(vals.min()), 2),
                "max": round(float(vals.max()), 2),
                "avg": round(float(vals.mean()), 2),
                "median": round(float(np.median(vals)), 2),
                "count": int(vals.size),
            })

        @app.route("/api/line")
        def api_line():
            try:
                x1 = int(request.args["x1"]); y1 = int(request.args["y1"])
                x2 = int(request.args["x2"]); y2 = int(request.args["y2"])
            except (KeyError, ValueError):
                abort(400)
            s = SHARED.snapshot()
            if s.thermal is None:
                return jsonify({"err": "no-frame"}), 503
            H, W = s.thermal.shape
            x1 = max(0, min(W - 1, x1)); x2 = max(0, min(W - 1, x2))
            y1 = max(0, min(H - 1, y1)); y2 = max(0, min(H - 1, y2))
            length = max(1, int(np.hypot(x2 - x1, y2 - y1)))
            xs = np.linspace(x1, x2, length).astype(int)
            ys = np.linspace(y1, y2, length).astype(int)
            vals = s.thermal[ys, xs]
            return jsonify({
                "samples": [round(float(v), 2) for v in vals.tolist()],
                "count": int(len(vals)),
                "min": round(float(vals.min()), 2),
                "max": round(float(vals.max()), 2),
                "avg": round(float(vals.mean()), 2),
                "length_px": length,
            })

        # ---- snapshot / recording ----
        @app.route("/api/snapshot", methods=["POST"])
        def api_snapshot():
            if self._recorder is None:
                return jsonify({"err": "recorder-disabled"}), 503
            snap = SHARED.snapshot()
            if snap.rendered is None:
                return jsonify({"err": "no-frame"}), 503
            res = self._recorder.snapshot(snap.rendered)
            if res.get("ok"):
                SHARED.append_event("snapshot", name=res.get("name"), bytes=res.get("bytes"))
            return jsonify(res)

        @app.route("/api/record/start", methods=["POST"])
        def api_record_start():
            if self._recorder is None:
                return jsonify({"err": "recorder-disabled"}), 503
            snap = SHARED.snapshot()
            if snap.rendered is None:
                return jsonify({"err": "no-frame"}), 503
            h, w = snap.rendered.shape[:2]
            fps = float(self.cfg().get("stream", {}).get("fps", 20))
            res = self._recorder.start((w, h), fps=fps)
            if res.get("ok"):
                SHARED.append_event("record_start", file=res.get("name"))
            return jsonify(res)

        @app.route("/api/record/stop", methods=["POST"])
        def api_record_stop():
            if self._recorder is None:
                return jsonify({"err": "recorder-disabled"}), 503
            res = self._recorder.stop()
            if res.get("ok"):
                SHARED.append_event(
                    "record_stop",
                    file=res.get("name"),
                    frames=res.get("frames"),
                    seconds=res.get("seconds"),
                )
            return jsonify(res)

        @app.route("/api/record/status")
        def api_record_status():
            if self._recorder is None:
                return jsonify({"recording": False, "err": "recorder-disabled"})
            return jsonify(self._recorder.status())

        @app.route("/api/files")
        def api_files():
            if self._recorder is None:
                return jsonify({"snapshots": [], "recordings": []})
            return jsonify(self._recorder.list_files())

        @app.route("/api/files/<kind>/<path:name>")
        def api_file_download(kind, name):
            if self._recorder is None:
                abort(404)
            base = {
                "snapshots":  self._recorder.snapshot_dir,
                "recordings": self._recorder.recording_dir,
            }.get(kind)
            if base is None:
                abort(404)
            full = os.path.abspath(os.path.join(base, name))
            if not full.startswith(os.path.abspath(base)):
                abort(403)
            if not os.path.isfile(full):
                abort(404)
            return send_file(full, as_attachment=True)

    # ---------- helpers ----------
    def _sample_thermal_frames(
        self, count: int = 20, timeout_s: float = 6.0
    ) -> list[np.ndarray]:
        """Pull `count` distinct thermal frames (by frame_idx), within `timeout_s`."""
        frames: list[np.ndarray] = []
        seen_idx = -1
        deadline = time.time() + timeout_s
        while len(frames) < count and time.time() < deadline:
            snap = SHARED.snapshot()
            if snap.thermal is None or snap.frame_idx == seen_idx:
                time.sleep(0.05)
                continue
            frames.append(snap.thermal.copy())
            seen_idx = snap.frame_idx
            time.sleep(0.05)
        return frames

    # ---------- MJPEG generator ----------
    def _mjpeg_gen(self):
        while True:
            cfg = self.cfg().get("stream", {})
            fps = max(1, int(cfg.get("fps", 20)))
            quality = int(cfg.get("jpeg_quality", 75))
            interval = 1.0 / fps

            snap = SHARED.snapshot()
            frame = snap.rendered
            if frame is None:
                time.sleep(0.1)
                continue
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            if not ok:
                time.sleep(0.1)
                continue
            jpg_bytes = jpg.tobytes()
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpg_bytes)).encode() + b"\r\n"
                b"\r\n"
                + jpg_bytes
                + b"\r\n"
            )
            time.sleep(interval)

    def run_threaded(self, port: int) -> None:
        t = threading.Thread(
            target=lambda: self.app.run(
                host="0.0.0.0", port=port, threaded=True, use_reloader=False
            ),
            daemon=True,
        )
        t.start()
        log.info(f"Web dashboard on :{port}/")
