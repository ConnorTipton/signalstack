"""Unit tests for the Ollama LLM client."""

import httpx
import pytest

from app.llm.ollama_client import OllamaClient

_BASE = "http://localhost:11434"


class _FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, routes: dict[str, httpx.Response]) -> None:
        self._routes = routes

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path in self._routes:
            return self._routes[path]
        raise AssertionError(f"No mock for {request.url}")


def _client(routes: dict[str, httpx.Response]) -> OllamaClient:
    transport = _FakeTransport(routes)
    http = httpx.AsyncClient(base_url=_BASE, transport=transport)
    return OllamaClient(base_url=_BASE, model="llama3.1:8b", http_client=http)


def _ollama_resp(response_text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "llama3.1:8b",
            "created_at": "2025-01-30T21:00:00Z",
            "response": response_text,
            "done": True,
            "total_duration": 3_000_000_000,
        },
    )


# ---------------------------------------------------------------------------
# generate — happy path
# ---------------------------------------------------------------------------


async def test_generate_returns_response_text():
    c = _client({"/api/generate": _ollama_resp('{"event_type": "earnings"}')})
    text, ms = await c.generate("classify this")
    assert text == '{"event_type": "earnings"}'


async def test_generate_returns_positive_processing_ms():
    c = _client({"/api/generate": _ollama_resp("ok")})
    _, ms = await c.generate("test")
    assert ms >= 0


async def test_generate_empty_response_text():
    c = _client({"/api/generate": _ollama_resp("")})
    text, _ = await c.generate("test")
    assert text == ""


# ---------------------------------------------------------------------------
# generate — error handling
# ---------------------------------------------------------------------------


async def test_generate_raises_on_non_200():
    c = _client({"/api/generate": httpx.Response(500, text="Internal Server Error")})
    with pytest.raises(httpx.HTTPStatusError):
        await c.generate("test")


async def test_generate_raises_on_connection_error():
    class _ErrorTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused")

    http = httpx.AsyncClient(base_url=_BASE, transport=_ErrorTransport())
    c = OllamaClient(base_url=_BASE, model="llama3.1:8b", http_client=http)
    with pytest.raises(httpx.ConnectError):
        await c.generate("test")
