"""High-level Start / Stop orchestration for the desktop app.

Exposes a SystemController that the JS API holds and calls. Start sequence:

  1. If Docker is not running, launch Docker Desktop and wait (up to 60s).
     Track whether *we* launched it so Stop can clean it up.
  2. start_postgres() + wait_for_postgres(10s) if not already running.
  3. Spawn API subprocess (uvicorn).
  4. Spawn workers subprocess (python -m app.main_workers).

Stop sequence:

  1. Stop workers, stop API.
  2. If we launched Docker: stop Postgres container, quit Docker Desktop.
     If Docker was already running when Start was clicked, leave it alone.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.desktop.controller import SubprocessController
from app.desktop.log_buffer import LogBuffer
from app.desktop.system_probes import (
    docker_desktop_installed,
    docker_running,
    launch_docker_desktop,
    postgres_running,
    quit_docker_desktop,
    start_postgres,
    stop_postgres,
    wait_for_docker,
    wait_for_postgres,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StartResult:
    ok: bool
    error: str | None


class SystemController:
    """Coordinates Docker, Postgres, workers, and API."""

    def __init__(self, *, repo_root: Path, log_buffer: LogBuffer) -> None:
        self._repo_root = repo_root
        self._log = log_buffer
        self._last_started_at: datetime | None = None
        self._we_launched_docker: bool = False

        self._api = SubprocessController(
            name="api",
            argv=[
                "uv",
                "run",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd=repo_root,
            log_buffer=log_buffer,
        )
        self._workers = SubprocessController(
            name="workers",
            argv=["uv", "run", "python", "-m", "app.main_workers"],
            cwd=repo_root,
            log_buffer=log_buffer,
        )

    @property
    def last_started_at(self) -> datetime | None:
        return self._last_started_at

    def start(self) -> StartResult:
        # Step 1-3: Docker
        if not docker_running():
            if not docker_desktop_installed():
                return StartResult(ok=False, error="Docker Desktop is not installed.")
            self._log.append("[system] launching Docker Desktop…")
            launch_docker_desktop()
            if not wait_for_docker(timeout=60.0, poll_interval=2.0):
                return StartResult(
                    ok=False,
                    error="Docker Desktop didn't start in time. Open it manually and try again.",
                )
            self._we_launched_docker = True
        else:
            self._we_launched_docker = False

        # Step 4: Postgres
        if not postgres_running(compose_dir=self._repo_root):
            self._log.append("[system] starting Postgres…")
            if not start_postgres(compose_dir=self._repo_root):
                return StartResult(ok=False, error="Postgres failed to start.")
            if not wait_for_postgres(compose_dir=self._repo_root, timeout=10.0):
                return StartResult(ok=False, error="Postgres didn't become ready in time.")

        # Step 5: API
        self._api.start()
        # Step 6: Workers
        self._workers.start()

        self._last_started_at = datetime.now(UTC)
        return StartResult(ok=True, error=None)

    def stop(self) -> None:
        self._workers.stop(timeout=10.0)
        self._api.stop(timeout=10.0)
        if self._we_launched_docker:
            self._log.append("[system] stopping Postgres…")
            stop_postgres(compose_dir=self._repo_root)
            self._log.append("[system] quitting Docker Desktop…")
            quit_docker_desktop()
            self._we_launched_docker = False

    def status(self) -> dict[str, str]:
        return {
            "docker": "running" if docker_running() else "stopped",
            "postgres": "running" if postgres_running(compose_dir=self._repo_root) else "stopped",
            "workers": self._workers.status(),
            "api": self._api.status(),
        }
