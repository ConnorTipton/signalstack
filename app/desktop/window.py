"""Build and run the PyWebView window for SignalStack.

The window loads web/SignalStack.html and exposes the JsApi as
`pywebview.api`. PyWebView's built-in http_server serves the file
over a local origin so the existing API CORS rules can match it
(see Task 14).
"""
from __future__ import annotations

import logging
from pathlib import Path

import webview

from app.desktop.js_api import JsApi
from app.desktop.log_buffer import LogBuffer
from app.desktop.system import SystemController

log = logging.getLogger(__name__)


def run(*, repo_root: Path) -> None:
    """Open the SignalStack desktop window. Blocks until the window closes."""
    html_path = repo_root / "web" / "SignalStack.html"
    if not html_path.exists():
        raise FileNotFoundError(f"Dashboard HTML missing: {html_path}")

    log_buffer = LogBuffer(max_lines=200)
    system = SystemController(repo_root=repo_root, log_buffer=log_buffer)
    js_api = JsApi(system=system, log_buffer=log_buffer)

    window = webview.create_window(
        title="SignalStack",
        url=str(html_path),
        js_api=js_api,
        width=1200,
        height=800,
        resizable=True,
    )

    def _on_closing() -> bool:
        # Stop subprocesses before the window exits so nothing is orphaned.
        log.info("Window closing — stopping system")
        try:
            system.stop()
        except Exception:  # noqa: BLE001 — log and proceed; closing must not hang
            log.exception("Error stopping system on window close")
        return True

    window.events.closing += _on_closing

    # http_server=True serves the HTML over http://localhost:<random_port>
    # which avoids file:// CORS issues with API calls to localhost:8000.
    webview.start(http_server=True)
