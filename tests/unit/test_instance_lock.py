"""Unit tests for app.desktop.instance_lock."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.desktop.instance_lock import InstanceLockError, acquire_lock


@pytest.fixture
def lock_path(tmp_path: Path) -> Path:
    return tmp_path / "desktop.lock"


def test_acquire_creates_lock_file(lock_path: Path) -> None:
    with acquire_lock(lock_path):
        assert lock_path.exists()
        # Lock file contains a PID (an integer)
        assert lock_path.read_text().strip().isdigit()


def test_lock_released_on_context_exit(lock_path: Path) -> None:
    with acquire_lock(lock_path):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_second_acquire_when_first_pid_alive_raises(lock_path: Path) -> None:
    lock_path.write_text(str(os.getpid()))
    # os.getpid() is alive — should be detected as a real conflict
    with pytest.raises(InstanceLockError, match="already running"), acquire_lock(lock_path):
        pass


def test_second_acquire_when_first_pid_dead_steals_lock(lock_path: Path) -> None:
    # Use a PID that's almost certainly not alive
    lock_path.write_text("999999")
    with (
        patch("app.desktop.instance_lock._pid_alive", return_value=False),
        acquire_lock(lock_path) as p,
    ):
        assert p == lock_path
        assert lock_path.read_text().strip() == str(os.getpid())


def test_lock_creates_parent_directory(tmp_path: Path) -> None:
    lock_path = tmp_path / "deep" / "path" / "desktop.lock"
    with acquire_lock(lock_path):
        assert lock_path.exists()
