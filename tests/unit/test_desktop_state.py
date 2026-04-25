"""Unit tests for app.core.desktop_state — sensitivity read/write."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import desktop_state


@pytest.fixture
def state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect desktop_state to a tmp file for isolation."""
    p = tmp_path / "desktop_state.json"
    monkeypatch.setattr(desktop_state, "STATE_FILE", p)
    return p


def test_read_sensitivity_missing_file_returns_medium(state_file: Path) -> None:
    assert not state_file.exists()
    assert desktop_state.read_sensitivity() == "medium"


def test_read_sensitivity_valid_high(state_file: Path) -> None:
    state_file.write_text(json.dumps({"sensitivity_mode": "high"}))
    assert desktop_state.read_sensitivity() == "high"


def test_read_sensitivity_valid_low(state_file: Path) -> None:
    state_file.write_text(json.dumps({"sensitivity_mode": "low"}))
    assert desktop_state.read_sensitivity() == "low"


def test_read_sensitivity_invalid_value_returns_default(
    state_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    state_file.write_text(json.dumps({"sensitivity_mode": "extreme"}))
    with caplog.at_level("WARNING"):
        assert desktop_state.read_sensitivity() == "medium"
    assert any("invalid sensitivity_mode" in r.message for r in caplog.records)


def test_read_sensitivity_malformed_json_returns_default(
    state_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    state_file.write_text("{not json")
    with caplog.at_level("WARNING"):
        assert desktop_state.read_sensitivity() == "medium"
    assert any("malformed" in r.message.lower() for r in caplog.records)


def test_read_sensitivity_missing_key_returns_default(state_file: Path) -> None:
    state_file.write_text(json.dumps({"other_key": "value"}))
    assert desktop_state.read_sensitivity() == "medium"


def test_write_sensitivity_creates_file(state_file: Path) -> None:
    assert not state_file.exists()
    desktop_state.write_sensitivity("high")
    assert state_file.exists()
    assert json.loads(state_file.read_text())["sensitivity_mode"] == "high"


def test_write_sensitivity_creates_parent_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    nested = tmp_path / "nested" / "dir" / "state.json"
    monkeypatch.setattr(desktop_state, "STATE_FILE", nested)
    desktop_state.write_sensitivity("low")
    assert nested.exists()
    assert json.loads(nested.read_text())["sensitivity_mode"] == "low"


def test_write_sensitivity_overwrites_existing(state_file: Path) -> None:
    state_file.write_text(json.dumps({"sensitivity_mode": "high"}))
    desktop_state.write_sensitivity("low")
    assert json.loads(state_file.read_text())["sensitivity_mode"] == "low"


def test_write_sensitivity_rejects_invalid_mode(state_file: Path) -> None:
    with pytest.raises(ValueError, match="invalid sensitivity mode"):
        desktop_state.write_sensitivity("extreme")  # type: ignore[arg-type]
    assert not state_file.exists()  # nothing written on bad input


def test_write_sensitivity_no_tmp_file_left_on_success(state_file: Path) -> None:
    desktop_state.write_sensitivity("medium")
    siblings = list(state_file.parent.iterdir())
    # Only the final file should exist — no .tmp leftover
    assert siblings == [state_file]


def test_round_trip(state_file: Path) -> None:
    for mode in ("high", "medium", "low"):
        desktop_state.write_sensitivity(mode)
        assert desktop_state.read_sensitivity() == mode
