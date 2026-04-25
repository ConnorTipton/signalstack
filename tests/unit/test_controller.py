"""Unit tests for app.desktop.controller — subprocess lifecycle."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from app.desktop.controller import SubprocessController
from app.desktop.log_buffer import LogBuffer

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def buf() -> LogBuffer:
    return LogBuffer(max_lines=200)


def test_status_stopped_initially(buf: LogBuffer) -> None:
    ctrl = SubprocessController(
        name="probe",
        argv=[sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=REPO_ROOT,
        log_buffer=buf,
    )
    assert ctrl.status() == "stopped"


def test_start_then_running(buf: LogBuffer) -> None:
    ctrl = SubprocessController(
        name="probe",
        argv=[sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=REPO_ROOT,
        log_buffer=buf,
    )
    ctrl.start()
    try:
        time.sleep(0.5)  # let it start
        assert ctrl.status() == "running"
    finally:
        ctrl.stop(timeout=5.0)


def test_stop_terminates_cleanly(buf: LogBuffer) -> None:
    ctrl = SubprocessController(
        name="probe",
        argv=[sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=REPO_ROOT,
        log_buffer=buf,
    )
    ctrl.start()
    time.sleep(0.5)
    ctrl.stop(timeout=5.0)
    assert ctrl.status() == "stopped"


def test_stop_kills_unresponsive_process(buf: LogBuffer) -> None:
    """A process that ignores SIGTERM gets SIGKILLed after timeout."""
    ctrl = SubprocessController(
        name="ignorant",
        argv=[
            sys.executable,
            "-c",
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
        ],
        cwd=REPO_ROOT,
        log_buffer=buf,
    )
    ctrl.start()
    time.sleep(0.5)
    t0 = time.time()
    ctrl.stop(timeout=1.0)
    elapsed = time.time() - t0
    assert ctrl.status() == "stopped"
    assert 0.9 < elapsed < 3.0  # killed shortly after timeout


def test_logs_captured(buf: LogBuffer) -> None:
    ctrl = SubprocessController(
        name="echoer",
        argv=[sys.executable, "-u", "-c", "print('hello from probe'); import time; time.sleep(60)"],
        cwd=REPO_ROOT,
        log_buffer=buf,
    )
    ctrl.start()
    try:
        # Wait up to 2s for output
        for _ in range(20):
            if any("hello from probe" in line for line in buf.recent(50)):
                break
            time.sleep(0.1)
        assert any("hello from probe" in line for line in buf.recent(50))
    finally:
        ctrl.stop(timeout=2.0)


def test_double_start_is_idempotent(buf: LogBuffer) -> None:
    ctrl = SubprocessController(
        name="probe",
        argv=[sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=REPO_ROOT,
        log_buffer=buf,
    )
    ctrl.start()
    pid1 = ctrl._proc.pid  # type: ignore[union-attr]
    ctrl.start()  # second start should no-op
    pid2 = ctrl._proc.pid  # type: ignore[union-attr]
    try:
        assert pid1 == pid2
    finally:
        ctrl.stop(timeout=5.0)


def test_stop_when_not_running_is_safe(buf: LogBuffer) -> None:
    ctrl = SubprocessController(
        name="probe",
        argv=[sys.executable, "-c", "pass"],
        cwd=REPO_ROOT,
        log_buffer=buf,
    )
    ctrl.stop(timeout=1.0)  # should not raise
    assert ctrl.status() == "stopped"
