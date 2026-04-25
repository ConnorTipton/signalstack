"""Unit tests for app.desktop.system_probes."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.desktop import system_probes


def test_docker_running_when_info_succeeds() -> None:
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        assert system_probes.docker_running() is True


def test_docker_not_running_when_info_fails() -> None:
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=1)
        assert system_probes.docker_running() is False


def test_docker_not_running_when_command_missing() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert system_probes.docker_running() is False


def test_docker_desktop_installed_true(tmp_path, monkeypatch):
    fake_app = tmp_path / "Docker.app"
    fake_app.mkdir()
    monkeypatch.setattr(system_probes, "DOCKER_APP_PATH", fake_app)
    assert system_probes.docker_desktop_installed() is True


def test_docker_desktop_installed_false(tmp_path, monkeypatch):
    monkeypatch.setattr(system_probes, "DOCKER_APP_PATH", tmp_path / "missing.app")
    assert system_probes.docker_desktop_installed() is False


def test_launch_docker_desktop_invokes_open() -> None:
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        system_probes.launch_docker_desktop()
        run.assert_called_once()
        args = run.call_args.args[0]
        assert args[:2] == ["open", "-a"]
        assert args[2] == "Docker"


def test_launch_docker_desktop_no_exception_when_open_missing() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError):
        system_probes.launch_docker_desktop()  # must not raise


def test_wait_for_docker_returns_true_when_already_up() -> None:
    with patch.object(system_probes, "docker_running", return_value=True):
        assert system_probes.wait_for_docker(timeout=5.0, poll_interval=0.1) is True


def test_wait_for_docker_returns_false_on_timeout() -> None:
    with patch.object(system_probes, "docker_running", return_value=False):
        assert system_probes.wait_for_docker(timeout=0.5, poll_interval=0.1) is False


def test_wait_for_docker_succeeds_after_a_few_polls() -> None:
    calls = {"n": 0}

    def fake_running() -> bool:
        calls["n"] += 1
        return calls["n"] >= 3

    with patch.object(system_probes, "docker_running", side_effect=fake_running):
        assert system_probes.wait_for_docker(timeout=5.0, poll_interval=0.1) is True
    assert calls["n"] >= 3


def test_postgres_running_parses_compose_ps() -> None:
    fake_output = '[{"Service":"postgres","State":"running","Health":"healthy"}]\n'
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout=fake_output)
        assert system_probes.postgres_running() is True


def test_postgres_running_false_when_state_not_running() -> None:
    fake_output = '[{"Service":"postgres","State":"exited"}]\n'
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout=fake_output)
        assert system_probes.postgres_running() is False


def test_postgres_running_false_when_compose_fails() -> None:
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stdout="")
        assert system_probes.postgres_running() is False
