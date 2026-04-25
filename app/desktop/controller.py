"""Manage a single long-running subprocess (workers or uvicorn).

Lifecycle:
    stopped -> start() -> running -> stop() -> stopped

A reader thread continuously consumes stdout (merged with stderr) and
pushes each line into a shared LogBuffer. The status is derived from
poll() on the underlying Popen.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path
from typing import Literal

from app.desktop.log_buffer import LogBuffer

log = logging.getLogger(__name__)

Status = Literal["stopped", "running"]


class SubprocessController:
    """Owns one subprocess: spawn, terminate, log capture."""

    def __init__(
        self,
        *,
        name: str,
        argv: list[str],
        cwd: Path,
        log_buffer: LogBuffer,
        env_extra: dict[str, str] | None = None,
    ) -> None:
        self._name = name
        self._argv = argv
        self._cwd = cwd
        self._log = log_buffer
        self._env_extra = env_extra or {}
        self._proc: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return  # already running

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"  # ensure subprocess writes lines promptly
            env.update(self._env_extra)

            self._log.append(f"[{self._name}] starting: {' '.join(self._argv)}")
            self._proc = subprocess.Popen(
                self._argv,
                cwd=str(self._cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._reader_thread = threading.Thread(
                target=self._read_output,
                args=(self._proc,),
                daemon=True,
                name=f"reader-{self._name}",
            )
            self._reader_thread.start()

    def stop(self, *, timeout: float = 10.0) -> None:
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self._proc = None
                return

            self._log.append(f"[{self._name}] stopping…")
            try:
                proc.terminate()
            except ProcessLookupError:
                self._proc = None
                return

            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._log.append(
                    f"[{self._name}] did not exit in {timeout}s — sending SIGKILL"
                )
                try:
                    proc.kill()
                    proc.wait(timeout=2.0)
                except (ProcessLookupError, subprocess.TimeoutExpired) as exc:
                    log.warning("Final kill of %s failed: %s", self._name, exc)

            self._log.append(f"[{self._name}] stopped (exit={proc.returncode})")
            self._proc = None

    def status(self) -> Status:
        # Lock released before poll() — holding it across a syscall would deadlock
        # against stop(), which also acquires the lock. The proc reference is stable
        # once captured (Python reference counting keeps the Popen alive).
        with self._lock:
            proc = self._proc
        if proc is None:
            return "stopped"
        if proc.poll() is None:
            return "running"
        return "stopped"

    def _read_output(self, proc: subprocess.Popen[str]) -> None:
        if proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                self._log.append(f"[{self._name}] {line.rstrip()}")
        except Exception as exc:  # noqa: BLE001 — defensive, isolate reader from owner
            log.warning("reader for %s crashed: %s", self._name, exc)
        finally:
            # Catch the final exit so status() reflects it on next poll
            proc.wait()
