"""MJPEG HTTP streamer — lightweight web preview of the processed frame."""

import threading
import time
import logging
import cv2
from flask import Flask, Response

log = logging.getLogger("stream")


class MjpegStreamer:
    def __init__(self, port=8080, fps=5, jpeg_quality=75):
        self.port = port
        self.fps = max(1, fps)
        self.quality = jpeg_quality
        self._frame = None
        self._lock = threading.Lock()
        self.app = Flask("thermal-stream")
        self._setup_routes()

    def _setup_routes(self):
        @self.app.route("/")
        def index():
            return (
                "<!doctype html><html><head><title>Thermal Tank Monitor</title>"
                "<style>body{background:#111;color:#eee;font-family:system-ui;margin:0;padding:1rem}"
                "img{image-rendering:pixelated;width:100%;max-width:768px;border:1px solid #333}"
                "</style></head><body><h2>Thermal Tank Monitor</h2>"
                "<img src='/stream.mjpg' alt='thermal stream'/>"
                "<p><a style='color:#4af' href='/healthz'>healthz</a></p>"
                "</body></html>"
            )

        @self.app.route("/stream.mjpg")
        def stream():
            return Response(self._generator(),
                            mimetype="multipart/x-mixed-replace; boundary=frame")

        @self.app.route("/healthz")
        def healthz():
            return ("ok", 200) if self._frame is not None else ("no-frame", 503)

    def _generator(self):
        interval = 1.0 / self.fps
        while True:
            with self._lock:
                f = None if self._frame is None else self._frame.copy()
            if f is None:
                time.sleep(0.1)
                continue
            ok, jpg = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, self.quality])
            if not ok:
                time.sleep(0.1)
                continue
            yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                   + jpg.tobytes() + b"\r\n")
            time.sleep(interval)

    def update(self, frame):
        with self._lock:
            self._frame = frame

    def run(self):
        t = threading.Thread(
            target=lambda: self.app.run(host="0.0.0.0", port=self.port,
                                        threaded=True, use_reloader=False),
            daemon=True,
        )
        t.start()
        log.info(f"MJPEG stream on :{self.port}/stream.mjpg")
