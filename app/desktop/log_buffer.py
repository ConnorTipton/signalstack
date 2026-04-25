"""Thread-safe ring buffer for subprocess stdout/stderr lines.

Both the workers and API subprocesses pipe their output into a shared
LogBuffer via reader threads. The Control tab in the UI fetches recent
lines via js_api.get_recent_logs() — read-only, no side effects.
"""
from __future__ import annotations

import threading
from collections import deque


class LogBuffer:
    """Bounded, thread-safe deque of log lines."""

    def __init__(self, max_lines: int = 200) -> None:
        self._buf: deque[str] = deque(maxlen=max_lines)
        self._lock = threading.Lock()

    def append(self, line: str) -> None:
        with self._lock:
            self._buf.append(line)

    def recent(self, n: int) -> list[str]:
        """Return up to the last n lines (oldest first)."""
        with self._lock:
            if n >= len(self._buf):
                return list(self._buf)
            return list(self._buf)[-n:]
