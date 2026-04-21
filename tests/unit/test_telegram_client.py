"""Unit tests for TelegramClient (Phase 7)."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.alerts.telegram import _SEND_MESSAGE_URL, _TIMEOUT, TelegramClient


def _client(token: str = "test_token", chat_id: str = "-100987") -> TelegramClient:
    return TelegramClient(bot_token=token, chat_id=chat_id)


def _ok_response() -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    return resp


def test_send_message_posts_to_bot_api():
    with patch("app.alerts.telegram.httpx.post") as mock_post:
        mock_post.return_value = _ok_response()
        _client(token="mytoken").send_message("hello")
    mock_post.assert_called_once()
    url = mock_post.call_args[0][0]
    assert "mytoken" in url
    assert "sendMessage" in url


def test_send_message_url_matches_template():
    with patch("app.alerts.telegram.httpx.post") as mock_post:
        mock_post.return_value = _ok_response()
        _client(token="abc123").send_message("x")
    url = mock_post.call_args[0][0]
    assert url == _SEND_MESSAGE_URL.format(token="abc123")


def test_send_message_payload_contains_chat_id_and_text():
    with patch("app.alerts.telegram.httpx.post") as mock_post:
        mock_post.return_value = _ok_response()
        _client(chat_id="-99999").send_message("Alert text")
    kwargs = mock_post.call_args[1]
    assert kwargs["json"]["chat_id"] == "-99999"
    assert kwargs["json"]["text"] == "Alert text"


def test_send_message_uses_configured_timeout():
    with patch("app.alerts.telegram.httpx.post") as mock_post:
        mock_post.return_value = _ok_response()
        _client().send_message("msg")
    assert mock_post.call_args[1]["timeout"] == _TIMEOUT


def test_send_message_raises_on_http_error():
    with patch("app.alerts.telegram.httpx.post") as mock_post:
        resp = MagicMock()
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "401 Unauthorized", request=MagicMock(), response=MagicMock()
        )
        mock_post.return_value = resp
        with pytest.raises(httpx.HTTPStatusError):
            _client().send_message("msg")
