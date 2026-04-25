"""Read/write the desktop app's runtime state file.

The state file lives at ~/.signalstack/desktop_state.json and currently
holds a single field: sensitivity_mode (one of "high", "medium", "low").

Both the desktop app (writes via js_api) and the alert worker (reads
each loop iteration) use this module. Reads are cheap — a few hundred
bytes of JSON per iteration — and need no caching.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

SensitivityMode = Literal["high", "medium", "low"]
_VALID_MODES: frozenset[str] = frozenset({"high", "medium", "low"})
_DEFAULT_MODE: SensitivityMode = "medium"

STATE_FILE: Path = Path.home() / ".signalstack" / "desktop_state.json"


def read_sensitivity() -> SensitivityMode:
    """Return the current sensitivity mode, with safe fallback to medium.

    Falls back to "medium" if the file is missing, malformed, or contains
    an unknown mode value. Logs a warning in malformed/unknown cases.
    """
    if not STATE_FILE.exists():
        return _DEFAULT_MODE

    try:
        raw = STATE_FILE.read_text()
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("desktop_state.json is malformed (%s) — using default 'medium'", exc)
        return _DEFAULT_MODE
    except OSError as exc:
        log.warning("desktop_state.json could not be read (%s) — using default 'medium'", exc)
        return _DEFAULT_MODE

    mode = data.get("sensitivity_mode")
    if mode in _VALID_MODES:
        return mode  # type: ignore[return-value]

    if mode is not None:
        log.warning("invalid sensitivity_mode %r — using default 'medium'", mode)
    return _DEFAULT_MODE


def write_sensitivity(mode: SensitivityMode) -> None:
    """Atomically write the sensitivity mode to the state file.

    Writes to <STATE_FILE>.tmp first, then renames to the final path.
    This ensures readers (e.g., the alert worker on its next loop
    iteration) never see a half-written file.

    Raises ValueError for unknown modes — the caller (js_api) should
    have validated already, but this is a defensive check so a bad
    write never reaches disk.
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"invalid sensitivity mode: {mode!r}")

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps({"sensitivity_mode": mode}, indent=2)

    fd, tmp_path = tempfile.mkstemp(
        prefix=STATE_FILE.name + ".",
        suffix=".tmp",
        dir=STATE_FILE.parent,
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload)
        os.replace(tmp_path, STATE_FILE)
    except Exception:
        # Clean up the tmp file if rename failed
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp_path)
        raise


_GRADES_BY_MODE: dict[SensitivityMode, frozenset[str]] = {
    "high": frozenset({"A"}),
    "medium": frozenset({"A", "B"}),
    "low": frozenset({"A", "B", "C"}),
}


def sensitivity_mode_to_grades(mode: SensitivityMode) -> frozenset[str]:
    """Map a sensitivity mode to the set of alert grades it permits.

    D-grade is never alerted in any mode — that's already enforced
    upstream by the cap logic in app/signals/scoring.py.
    """
    return _GRADES_BY_MODE[mode]
