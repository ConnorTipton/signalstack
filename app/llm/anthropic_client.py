"""Anthropic Claude client for LLM news labeling.

Matches the same generate() interface contract used by the LabelWorker.
"""

from __future__ import annotations

import logging
import time

import anthropic

log = logging.getLogger(__name__)


class AnthropicClient:
    """Thin wrapper around the Anthropic Messages API.

    Parameters
    ----------
    api_key:
        Anthropic API key.
    model:
        Model ID (e.g. "claude-haiku-4-5-20251001").
    max_tokens:
        Maximum tokens in the response. 256 is plenty for structured labels.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 256,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(self, prompt: str) -> tuple[str, int]:
        """Send prompt to Claude and return (response_text, processing_ms).

        Raises anthropic.APIError on failure so the caller can catch and log
        without crashing the worker loop.
        """
        t0 = time.monotonic()
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        processing_ms = int((time.monotonic() - t0) * 1000)
        response_text = message.content[0].text if message.content else ""
        return response_text, processing_ms

    async def aclose(self) -> None:
        await self._client.close()

    async def __aenter__(self) -> AnthropicClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
