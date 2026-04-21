"""Ollama local LLM client.

Sends prompts to a locally-running Ollama instance via its HTTP API and
returns the response text plus wall-clock processing time in milliseconds.

Cloud LLM fallback is deferred to Phase 5. The label_worker accepts any
callable matching the generate() signature, so swapping backends requires
no changes to worker logic.
"""

from __future__ import annotations

import logging
import time

import httpx

log = logging.getLogger(__name__)

_GENERATE_PATH = "/api/generate"


class OllamaClient:
    """HTTP client for the Ollama /api/generate endpoint.

    Parameters
    ----------
    base_url:
        URL of the Ollama server (e.g. "http://localhost:11434").
    model:
        Model name to use (e.g. "llama3.1:8b").
    http_client:
        Injected httpx.AsyncClient for testing. When None, a default client
        is created and owned by this instance.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._model = model
        self._owns_client = http_client is None
        self._http = http_client or httpx.AsyncClient(
            base_url=base_url,
            timeout=120.0,  # local inference can be slow
        )

    async def generate(self, prompt: str) -> tuple[str, int]:
        """Send prompt to Ollama and return (response_text, processing_ms).

        Raises httpx.HTTPError on connection or non-200 response so the
        caller can catch and log without crashing the worker loop.
        """
        t0 = time.monotonic()
        resp = await self._http.post(
            _GENERATE_PATH,
            json={"model": self._model, "prompt": prompt, "stream": False},
        )
        resp.raise_for_status()
        processing_ms = int((time.monotonic() - t0) * 1000)

        data = resp.json()
        response_text = data.get("response", "")
        return response_text, processing_ms

    async def aclose(self) -> None:
        if self._owns_client:
            await self._http.aclose()

    async def __aenter__(self) -> OllamaClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
