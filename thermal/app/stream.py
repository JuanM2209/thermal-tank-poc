"""MJPEG + JSON API server.

- GET  /                        -> SPA dashboard
- GET  /stream.mjpg             -> live palette+overlay stream
- GET  /api/state               -> latest readings
- GET  /api/temp?x=INT&y=INT    -> temperature at sensor pixel (°C)
- GET  /api/config              -> merged config
- PATCH /api/config             -> deep-merge partial update (palette, overlays, fps, ...)
- GET  /api/tanks               -> current tanks
- POST /api/tanks               -> add a tank
- PATCH /api/tanks/<id>         -> update fields (name, medium, roi, min_temp_delta)
- DELETE /api/tanks/<id>        -> remove
- GET  /api/events?since=SEQ    -> event log
- GET  /healthz                 -> ok/503
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time

import cv2
import numpy as np
from flask import Flask, Response, abort, jsonify, request

from state import SHARED
from webui import INDEX_HTML

log = logging.getLogger("stream")


class WebServer:
    def __init__(self, config: dict, on_config_change=None, persist_path=None):
        self._cfg = config
        self._cfg_lock = threading.Lock()
        self._on_change = on_config_change or (lambda: None)
        self._persist_path = persist_path
        self.app = Flask("thermal")
        self.app.config["JSON_SORT_KEYS"] = False
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

    def _persist(self):
        if not self._persist_path:
            return
        try:
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(self._cfg, f, indent=2)
        except Exception as e:
            log.warning(f"persist failed: {e}")

    def apply_patch(self, patch: dict):
        with self._cfg_lock:
            self._deep_merge(self._cfg, patch)
            self._persist()
        self._on_change()
        SHARED.bump_cfg()
        SHARED.append_event("config_change", keys=list(patch.keys()))

    # ---------- Routes ----------
    def _setup_routes(self):
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
            return Response(self._mjpeg_gen(),
                            mimetype="multipart/x-mixed-replace; boundary=frame")

        @app.route("/api/state")
        def api_state():
            s = SHARED.snapshot()
            h = w = 0
            if s.rendered is not None:
                h, w = s.rendered.shape[:2]
            return jsonify({
                "ts": s.ts,
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
            # 3x3 neighbourhood median to smooth noise
            x0, x1 = max(0, x-1), min(W, x+2)
            y0, y1 = max(0, y-1), min(H, y+2)
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
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                   + jpg.tobytes() + b"\r\n")
            time.sleep(interval)

    def run_threaded(self, port: int):
        t = threading.Thread(
            target=lambda: self.app.run(host="0.0.0.0", port=port,
                                        threaded=True, use_reloader=False),
            daemon=True,
        )
        t.start()
        log.info(f"Web dashboard on :{port}/")
