"""Unit tests for app.desktop.log_buffer."""
from __future__ import annotations

from app.desktop.log_buffer import LogBuffer


def test_appends_and_returns_lines() -> None:
    buf = LogBuffer(max_lines=10)
    buf.append("line 1")
    buf.append("line 2")
    assert buf.recent(50) == ["line 1", "line 2"]


def test_caps_at_max_lines() -> None:
    buf = LogBuffer(max_lines=3)
    for i in range(5):
        buf.append(f"line {i}")
    assert buf.recent(50) == ["line 2", "line 3", "line 4"]


def test_recent_returns_last_n() -> None:
    buf = LogBuffer(max_lines=100)
    for i in range(20):
        buf.append(f"line {i}")
    assert buf.recent(5) == [f"line {i}" for i in range(15, 20)]


def test_recent_when_buffer_smaller_than_n() -> None:
    buf = LogBuffer(max_lines=100)
    buf.append("only one")
    assert buf.recent(50) == ["only one"]


def test_thread_safe_under_concurrent_appends() -> None:
    """Smoke test: many threads appending should not raise or lose data integrity."""
    import threading

    buf = LogBuffer(max_lines=10000)

    def worker(start: int) -> None:
        for i in range(100):
            buf.append(f"t{start}-{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = buf.recent(2000)
    assert len(lines) == 1000  # 10 threads × 100 lines each
