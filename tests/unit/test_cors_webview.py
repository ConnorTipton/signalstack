"""Verify CORS allows the webview origin pattern.

PyWebView serves the dashboard at http://127.0.0.1:<random_port>. The
API must accept those origins so the embedded JS can call /api/v1/...
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_cors_allows_localhost_random_port() -> None:
    response = client.options(
        "/api/v1/alerts",
        headers={
            "Origin": "http://127.0.0.1:54321",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") in (
        "http://127.0.0.1:54321",
        "*",
    )


def test_cors_still_allows_existing_dev_server() -> None:
    response = client.options(
        "/api/v1/alerts",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") in (
        "http://localhost:3000",
        "*",
    )
