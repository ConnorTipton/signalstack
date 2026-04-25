"""Unit tests for app.desktop.js_api."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.desktop.js_api import JsApi
from app.desktop.log_buffer import LogBuffer
from app.desktop.system import StartResult


@pytest.fixture
def js_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JsApi:
    state_path = tmp_path / "desktop_state.json"
    from app.core import desktop_state
    monkeypatch.setattr(desktop_state, "STATE_FILE", state_path)

    buf = LogBuffer(max_lines=200)
    system = MagicMock()
    return JsApi(system=system, log_buffer=buf)


def test_get_status_delegates_to_system(js_api: JsApi) -> None:
    js_api._system.status.return_value = {
        "docker": "running",
        "postgres": "running",
        "workers": "stopped",
        "api": "stopped",
    }
    assert js_api.get_status()["workers"] == "stopped"


def test_start_system_returns_dict_on_success(js_api: JsApi) -> None:
    js_api._system.start.return_value = StartResult(ok=True, error=None)
    result = js_api.start_system()
    assert result == {"ok": True, "error": None}


def test_start_system_returns_error_on_failure(js_api: JsApi) -> None:
    js_api._system.start.return_value = StartResult(ok=False, error="Docker not installed.")
    result = js_api.start_system()
    assert result == {"ok": False, "error": "Docker not installed."}


def test_stop_system_calls_system_stop(js_api: JsApi) -> None:
    js_api.stop_system()
    js_api._system.stop.assert_called_once()


def test_get_recent_logs_returns_lines(js_api: JsApi) -> None:
    js_api._log.append("first")
    js_api._log.append("second")
    assert js_api.get_recent_logs(50) == ["first", "second"]


def test_get_sensitivity_returns_default_when_unset(js_api: JsApi) -> None:
    assert js_api.get_sensitivity() == "medium"


def test_set_sensitivity_writes_and_returns_new_value(js_api: JsApi) -> None:
    result = js_api.set_sensitivity("high")
    assert result == {"ok": True, "mode": "high", "error": None}
    assert js_api.get_sensitivity() == "high"


def test_set_sensitivity_rejects_unknown_value(js_api: JsApi) -> None:
    result = js_api.set_sensitivity("extreme")
    assert result["ok"] is False
    assert "invalid" in result["error"].lower()
    # Original value unchanged
    assert js_api.get_sensitivity() == "medium"
