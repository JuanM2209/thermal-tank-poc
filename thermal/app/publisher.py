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
BACKOFF_BASE_S = 1.0
BACKOFF_MAX_S = 30.0
FAILS_BEFORE_BACKOFF = 2
WARN_EVERY_N_FAILS = 50  # Only log one warning every N consecutive failures.
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
        timeout: float = 0.5,
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
        # Backoff state (only touched by the worker thread).
        self._consecutive_fails = 0
        self._next_retry_at = 0.0
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()
        log.info(f"HTTP publisher -> {self.endpoint} (site={site_id})")

    def _worker(self) -> None:
        while self._running:
            now = time.monotonic()
            # Under backoff: drop what's queued and sleep until the retry slot.
            if self._consecutive_fails >= FAILS_BEFORE_BACKOFF and now < self._next_retry_at:
                with self._lock:
                    self._queue.clear()
                time.sleep(min(WORKER_SLEEP, self._next_retry_at - now))
                continue
            with self._lock:
                batch = self._queue[:]
                self._queue.clear()
            for item in batch:
                self._post(item)
                # If the endpoint went down mid-batch, stop — next loop applies
                # backoff and clears the rest instead of pounding the socket.
                if self._consecutive_fails >= FAILS_BEFORE_BACKOFF:
                    break
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
            self._note_failure(f"POST failed: {e}")
        except Exception as e:
            self._note_failure(f"POST error: {e}")
        else:
            if self._consecutive_fails:
                log.info(
                    "POST succeeded after %d failures — endpoint back online",
                    self._consecutive_fails,
                )
            self._consecutive_fails = 0
            self._next_retry_at = 0.0

    def _note_failure(self, msg: str) -> None:
        self._consecutive_fails += 1
        # Exponential backoff capped at BACKOFF_MAX_S.
        delay = min(BACKOFF_MAX_S, BACKOFF_BASE_S * (2 ** max(0, self._consecutive_fails - FAILS_BEFORE_BACKOFF)))
        self._next_retry_at = time.monotonic() + delay
        # First failure and every Nth after that get logged — don't spam.
        if self._consecutive_fails == 1 or (self._consecutive_fails % WARN_EVERY_N_FAILS) == 0:
            log.warning(
                "%s (fails=%d, backoff=%.1fs)",
                msg,
                self._consecutive_fails,
                delay,
            )

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
