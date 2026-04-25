"""Unit tests for app.desktop.system — Start/Stop orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.desktop.log_buffer import LogBuffer
from app.desktop.system import StartResult, SystemController


@pytest.fixture
def buf() -> LogBuffer:
    return LogBuffer(max_lines=200)


def _make_controller(buf: LogBuffer) -> SystemController:
    return SystemController(repo_root=MagicMock(), log_buffer=buf)


def test_start_when_docker_already_up_and_postgres_up(buf: LogBuffer) -> None:
    ctrl = _make_controller(buf)
    with (
        patch("app.desktop.system.docker_running", return_value=True),
        patch("app.desktop.system.postgres_running", return_value=True),
        patch.object(ctrl._workers, "start") as ws,
        patch.object(ctrl._api, "start") as as_,
    ):
        result = ctrl.start()
    assert result == StartResult(ok=True, error=None)
    ws.assert_called_once()
    as_.assert_called_once()


def test_start_aborts_when_docker_not_installed(buf: LogBuffer) -> None:
    ctrl = _make_controller(buf)
    with (
        patch("app.desktop.system.docker_running", return_value=False),
        patch("app.desktop.system.docker_desktop_installed", return_value=False),
    ):
        result = ctrl.start()
    assert result.ok is False
    assert "not installed" in (result.error or "").lower()


def test_start_launches_docker_when_not_running(buf: LogBuffer) -> None:
    ctrl = _make_controller(buf)
    with (
        patch("app.desktop.system.docker_running", return_value=False),
        patch("app.desktop.system.docker_desktop_installed", return_value=True),
        patch("app.desktop.system.launch_docker_desktop") as launch,
        patch("app.desktop.system.wait_for_docker", return_value=True),
        patch("app.desktop.system.start_postgres", return_value=True),
        patch("app.desktop.system.wait_for_postgres", return_value=True),
        patch.object(ctrl._workers, "start"),
        patch.object(ctrl._api, "start"),
    ):
        result = ctrl.start()
    assert result.ok is True
    launch.assert_called_once()


def test_start_aborts_when_docker_wait_times_out(buf: LogBuffer) -> None:
    ctrl = _make_controller(buf)
    with (
        patch("app.desktop.system.docker_running", return_value=False),
        patch("app.desktop.system.docker_desktop_installed", return_value=True),
        patch("app.desktop.system.launch_docker_desktop"),
        patch("app.desktop.system.wait_for_docker", return_value=False),
    ):
        result = ctrl.start()
    assert result.ok is False
    assert "didn't start in time" in (result.error or "")


def test_start_aborts_when_postgres_fails(buf: LogBuffer) -> None:
    ctrl = _make_controller(buf)
    with (
        patch("app.desktop.system.docker_running", return_value=True),
        patch("app.desktop.system.postgres_running", return_value=False),
        patch("app.desktop.system.start_postgres", return_value=False),
    ):
        result = ctrl.start()
    assert result.ok is False
    assert "postgres" in (result.error or "").lower()


def test_stop_terminates_both_subprocesses(buf: LogBuffer) -> None:
    ctrl = _make_controller(buf)
    with patch.object(ctrl._workers, "stop") as ws, patch.object(ctrl._api, "stop") as as_:
        ctrl.stop()
    ws.assert_called_once()
    as_.assert_called_once()


def test_status_combines_components(buf: LogBuffer) -> None:
    ctrl = _make_controller(buf)
    with (
        patch("app.desktop.system.docker_running", return_value=True),
        patch("app.desktop.system.postgres_running", return_value=True),
        patch.object(ctrl._workers, "status", return_value="running"),
        patch.object(ctrl._api, "status", return_value="stopped"),
    ):
        s = ctrl.status()
    assert s == {
        "docker": "running",
        "postgres": "running",
        "workers": "running",
        "api": "stopped",
    }
