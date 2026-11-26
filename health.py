"""
health.py - per-source health state, /health endpoint and bad-data alerting.

Each ingestion service keeps one SourceHealth. It remembers when the last
fetch succeeded, counts bad readings, and logs a single
BAD_DATA_THRESHOLD_EXCEEDED error when more than `threshold` bad readings
arrive within one hour (a real alerting rule would watch for this log line).
"""

import json
import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import jsonlog

log = logging.getLogger("health")

THRESHOLD = 10
WINDOW_SECONDS = 3600


class SourceHealth:
    def __init__(self, source, count_fn, threshold=THRESHOLD, window=WINDOW_SECONDS):
        self.source = source
        self.count_fn = count_fn  # returns the running bad_data_count of the service
        self.threshold = threshold
        self.window = window
        self.last_successful_fetch = None
        self._recent = deque()  # timestamps of bad readings inside the window
        self._alerted = False
        self._lock = threading.Lock()

    def fetch_ok(self):
        with self._lock:
            self.last_successful_fetch = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def record_bad(self, now=None):
        """Call once per bad reading. Logs ONE error when the hourly count passes the threshold."""
        now = time.time() if now is None else now
        with self._lock:
            self._recent.append(now)
            while self._recent and now - self._recent[0] > self.window:
                self._recent.popleft()
            in_window = len(self._recent)
            if in_window > self.threshold and not self._alerted:
                self._alerted = True
                jsonlog.event(log, logging.ERROR, "BAD_DATA_THRESHOLD_EXCEEDED",
                              source=self.source, count=in_window)
            elif in_window <= self.threshold:
                self._alerted = False
        return in_window

    def snapshot(self):
        with self._lock:
            return {
                "last_successful_fetch": self.last_successful_fetch,
                "bad_data_count": self.count_fn(),
                "source": self.source,
            }


def serve(source_health, port):
    """Start GET /health on a background thread and return the server."""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != "/health":
                self.send_response(404)
                self.end_headers()
                return
            body = json.dumps(source_health.snapshot()).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # keep stdout clean: only JSON events
            pass

    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server