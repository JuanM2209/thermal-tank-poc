"""HTTP POST publisher — sends tank readings directly to a Node-RED HTTP endpoint.
No MQTT broker needed — Node-RED already runs on the Nucleus.
"""

import json
import logging
import time
import threading
import urllib.request
import urllib.error

log = logging.getLogger("http")


class HttpPublisher:
    def __init__(self, endpoint, timeout=3.0, max_queue=500):
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self._queue = []
        self._lock = threading.Lock()
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        log.info(f"HTTP publisher -> {self.endpoint}")

    def _worker(self):
        while self._running:
            with self._lock:
                batch = self._queue[:]
                self._queue.clear()
            for item in batch:
                self._post(item)
            time.sleep(0.2)

    def _post(self, payload):
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

    def publish(self, results):
        now_ms = int(time.time() * 1000)
        payload = {
            "ts": now_ms,
            "tanks": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "medium": r.get("medium", "unknown"),
                    "level_pct": r["level_pct"],
                    "temp_min": r["temp_min"],
                    "temp_max": r["temp_max"],
                    "temp_avg": r["temp_avg"],
                    "gradient_peak": r["gradient_peak"],
                    "confidence": r["confidence"],
                }
                for r in results
            ],
        }
        with self._lock:
            if len(self._queue) < 500:
                self._queue.append(payload)

    def stop(self):
        self._running = False
