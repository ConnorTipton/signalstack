"""Tradier HTTP streaming session management.

Tradier streams market events over an HTTP chunked-transfer connection (not
WebSocket). Workflow:
  1. POST /v1/markets/events/session  →  get session_id + stream_url
  2. POST stream_url with sessionid + symbols  →  read newline-delimited JSON
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from app.providers.base import ProviderError

_SESSION_PATH = "/v1/markets/events/session"


class TradierStreamError(ProviderError):
    pass


async def create_session(api_token: str, base_url: str) -> tuple[str, str]:
    """Create a Tradier streaming session via REST.

    Returns ``(session_id, stream_url)``.
    Raises ``TradierStreamError`` immediately if ``api_token`` is falsy so
    the worker gets a clear error rather than a cryptic 401.
    """
    if not api_token:
        raise TradierStreamError("TRADIER_API_TOKEN not configured")
    async with httpx.AsyncClient(
        base_url=base_url,
        headers={
            "Authorization": f"Bearer {api_token}",
            "Accept": "application/json",
        },
        timeout=10.0,
    ) as http:
        resp = await http.post(_SESSION_PATH)
        if resp.status_code != 200:
            raise TradierStreamError(
                f"Session creation failed ({resp.status_code}): {resp.text[:200]}"
            )
        data = resp.json()
        stream = data["stream"]
        return stream["sessionid"], stream["url"]


async def stream_market_events(
    session_id: str,
    stream_url: str,
    symbols: list[str],
) -> AsyncIterator[dict]:
    """Connect to Tradier's HTTP streaming endpoint and yield parsed JSON events.

    Filters for quote events server-side. Malformed lines are silently skipped.
    Raises ``TradierStreamError`` if the connection is refused.
    """
    timeout = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)
    http = httpx.AsyncClient(timeout=timeout)
    async with (
        http,
        http.stream(
            "POST",
            stream_url,
            data={
                "sessionid": session_id,
                "symbols": ",".join(symbols),
                "linebreak": "true",
                "filter": "quote",
            },
            headers={"Accept": "application/json"},
        ) as response,
    ):
        if response.status_code != 200:
            body = await response.aread()
            raise TradierStreamError(f"Stream refused ({response.status_code}): {body[:200]!r}")
        async for raw_line in response.aiter_lines():
            stripped = raw_line.strip()
            if not stripped:
                continue
            try:
                yield json.loads(stripped)
            except json.JSONDecodeError:
                continue
