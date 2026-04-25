"""Helpers to probe and launch Docker / Postgres for the desktop app.

All functions are designed to be safe to call from any thread and to
fail gracefully (return False rather than raise) when underlying
commands are missing or fail.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)

DOCKER_APP_PATH: Path = Path("/Applications/Docker.app")


def docker_running() -> bool:
    """Return True if `docker info` succeeds (the daemon is up)."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=2.0,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def docker_desktop_installed() -> bool:
    """Return True if /Applications/Docker.app exists."""
    return DOCKER_APP_PATH.exists()


def launch_docker_desktop() -> None:
    """Launch Docker Desktop on macOS (`open -a Docker`).

    Returns immediately — the daemon takes additional time to be ready.
    Caller should follow up with wait_for_docker().
    Does nothing (no exception) if `open` is not available.
    """
    try:
        subprocess.run(["open", "-a", "Docker"], check=False)
    except FileNotFoundError:
        log.warning("launch_docker_desktop: `open` not found (non-macOS?)")


def wait_for_docker(*, timeout: float = 60.0, poll_interval: float = 2.0) -> bool:
    """Poll docker_running() until it returns True or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if docker_running():
            return True
        time.sleep(poll_interval)
    return False


def postgres_running(*, compose_dir: Path | None = None) -> bool:
    """Return True if `docker compose ps postgres` reports state=running."""
    cmd = ["docker", "compose", "ps", "postgres", "--format", "json"]
    cwd = str(compose_dir) if compose_dir else None
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5.0, cwd=cwd
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0 or not result.stdout.strip():
        return False
    try:
        # Newer compose versions emit a JSON array; older versions emit JSONL.
        stripped = result.stdout.strip()
        if stripped.startswith("["):
            entries = json.loads(stripped)
        else:
            entries = [json.loads(line) for line in stripped.splitlines() if line.strip()]
    except json.JSONDecodeError:
        return False
    return any(e.get("State") == "running" for e in entries)


def start_postgres(*, compose_dir: Path) -> bool:
    """Run `docker compose up -d postgres`. Returns True on success."""
    try:
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "postgres"],
            cwd=str(compose_dir),
            capture_output=True,
            text=True,
            timeout=30.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("start_postgres failed: %s", exc)
        return False
    if result.returncode != 0:
        log.warning("docker compose up returned %d: %s", result.returncode, result.stderr)
        return False
    return True


def wait_for_postgres(*, compose_dir: Path, timeout: float = 10.0, poll_interval: float = 0.5) -> bool:
    """Poll postgres_running() until True or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if postgres_running(compose_dir=compose_dir):
            return True
        time.sleep(poll_interval)
    return False
