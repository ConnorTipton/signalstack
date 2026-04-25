"""Read/write the desktop app's runtime state file.

The state file lives at ~/.signalstack/desktop_state.json and currently
holds a single field: sensitivity_mode (one of "high", "medium", "low").

Both the desktop app (writes via js_api) and the alert worker (reads
each loop iteration) use this module. Reads are cheap — a few hundred
bytes of JSON per iteration — and need no caching.
"""
from __future__ import annotations

import json
import logging
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
