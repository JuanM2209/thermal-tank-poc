"""HTTP POST publisher -> Node-RED ingest endpoint.

Timestamp is ALWAYS milliseconds since epoch. Downstream code (Node-RED,
dashboards) should never do unit math.
"""

from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger("http")

MAX_QUEUE = 500
WORKER_SLEEP = 0.2
PAYLOAD_FIELDS = (
    "id", "name", "medium", "medium_declared", "medium_confidence",
    "level_pct", "level_pct_raw",
    "temp_min", "temp_max", "temp_avg",
    "gradient_peak", "confidence",
    "geometry", "reading", "roi",
)


class HttpPublisher:
    def __init__(
        self,
        endpoint: str,
        timeout: float = 3.0,
        site_id: str = "unknown",
        max_queue: int = MAX_QUEUE,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.site_id = site_id
        self._max_queue = max_queue
        self._queue: list[dict] = []
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        log.info(f"HTTP publisher -> {self.endpoint} (site={site_id})")

    def _worker(self) -> None:
        while self._running:
            with self._lock:
                batch = self._queue[:]
                self._queue.clear()
            for item in batch:
                self._post(item)
            time.sleep(WORKER_SLEEP)

    def _post(self, payload: dict) -> None:
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp.read()
        except urllib.error.URLError as e:
            log.warning(f"POST failed: {e}")
        except Exception as e:
            log.warning(f"POST error: {e}")

    def publish(self, results: list[dict], calibration: dict | None = None) -> None:
        now_ms = int(time.time() * 1000)
        tanks: list[dict] = []
        for r in results:
            tank: dict = {k: r.get(k) for k in PAYLOAD_FIELDS if k in r}
            if calibration:
                tank["calibration"] = calibration
            tanks.append(tank)
        payload = {
            "ts": now_ms,
            "site_id": self.site_id,
            "tanks": tanks,
        }
        with self._lock:
            if len(self._queue) < self._max_queue:
                self._queue.append(payload)

    def stop(self) -> None:
        self._running = False
