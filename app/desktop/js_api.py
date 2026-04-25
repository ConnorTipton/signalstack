"""JavaScript-callable API exposed to the PyWebView frontend.

PyWebView automatically converts public methods on this object into
`pywebview.api.<name>()` callables in JS. All return values must be
JSON-serializable. Errors are returned as dicts with ok=False rather
than raised — the JS side cannot easily catch Python exceptions.
"""

from __future__ import annotations

import logging

from app.core.desktop_state import (
    SensitivityMode,
    read_sensitivity,
    write_sensitivity,
)
from app.desktop.log_buffer import LogBuffer
from app.desktop.system import SystemController

log = logging.getLogger(__name__)


class JsApi:
    """Public surface called from the dashboard JS via pywebview.api."""

    def __init__(self, *, system: SystemController, log_buffer: LogBuffer) -> None:
        self._system = system
        self._log = log_buffer

    # --- System control ------------------------------------------------

    def start_system(self) -> dict[str, object]:
        result = self._system.start()
        return {"ok": result.ok, "error": result.error}

    def stop_system(self) -> dict[str, object]:
        self._system.stop()
        return {"ok": True, "error": None}

    def get_status(self) -> dict[str, str]:
        return self._system.status()

    def get_recent_logs(self, n: int = 50) -> list[str]:
        return self._log.recent(int(n))

    def get_last_started_at(self) -> str | None:
        ts = self._system.last_started_at
        return ts.isoformat() if ts else None

    # --- Sensitivity ---------------------------------------------------

    def get_sensitivity(self) -> SensitivityMode:
        return read_sensitivity()

    def set_sensitivity(self, mode: str) -> dict[str, object]:
        if mode not in ("high", "medium", "low"):
            return {
                "ok": False,
                "error": f"invalid sensitivity mode: {mode!r}",
                "mode": read_sensitivity(),
            }
        try:
            write_sensitivity(mode)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 — must surface to JS, not crash window
            log.exception("failed to write sensitivity")
            return {"ok": False, "error": str(exc), "mode": read_sensitivity()}
        return {"ok": True, "mode": mode, "error": None}
