"""Single-instance lock for the SignalStack desktop app.

Prevents two SignalStack windows from running at once (which would
collide on port 8000 and other shared state).
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path


class InstanceLockError(RuntimeError):
    """Raised when another instance already holds the lock."""


def _pid_alive(pid: int) -> bool:
    """Return True if a process with this PID is currently alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
    return True


@contextmanager
def acquire_lock(lock_path: Path) -> Iterator[Path]:
    """Acquire an exclusive lock file. Releases on context exit.

    If the lock file exists and contains an alive PID, raises
    InstanceLockError. If it exists but the PID is dead (stale lock),
    the lock is silently stolen — the previous instance crashed.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.exists():
        try:
            existing = int(lock_path.read_text().strip() or "0")
        except ValueError:
            existing = 0
        if _pid_alive(existing):
            raise InstanceLockError(
                f"SignalStack is already running (PID {existing})."
            )
        # Stale lock — fall through and overwrite

    lock_path.write_text(str(os.getpid()))
    try:
        yield lock_path
    finally:
        with suppress(FileNotFoundError):
            lock_path.unlink()
