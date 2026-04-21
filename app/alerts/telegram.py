"""Telegram Bot API client — wraps the sendMessage endpoint."""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

_SEND_MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"
_TIMEOUT = 10.0


class TelegramClient:
    """Thin wrapper around Telegram Bot API sendMessage.

    Raises httpx.HTTPStatusError on 4xx/5xx responses.
    """

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._token = bot_token
        self._chat_id = chat_id

    def send_message(self, text: str) -> None:
        """Send a plain-text message to the configured chat."""
        url = _SEND_MESSAGE_URL.format(token=self._token)
        resp = httpx.post(
            url,
            json={"chat_id": self._chat_id, "text": text},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        log.debug("Telegram: sent message (%d chars)", len(text))
