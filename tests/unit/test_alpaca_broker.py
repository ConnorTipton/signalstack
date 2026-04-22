"""Unit tests for AlpacaBrokerClient (Phase 8)."""

from unittest.mock import MagicMock, patch

import pytest

from app.execution.alpaca_broker import AlpacaBrokerClient, AlpacaBrokerError


def _client(paper: bool = True) -> AlpacaBrokerClient:
    return AlpacaBrokerClient(api_key="key", secret_key="secret", paper=paper)


def _ok(body: dict) -> MagicMock:
    resp = MagicMock()
    resp.is_success = True
    resp.json.return_value = body
    return resp


def _err(status_code: int) -> MagicMock:
    resp = MagicMock()
    resp.is_success = False
    resp.status_code = status_code
    resp.text = "error"
    return resp


# ---------------------------------------------------------------------------
# submit_limit_order
# ---------------------------------------------------------------------------


def test_rejects_live_trading_mode():
    with pytest.raises(ValueError, match="Live Alpaca trading is disabled"):
        _client(paper=False)


def test_submit_limit_order_posts_to_orders_endpoint():
    with patch("app.execution.alpaca_broker.httpx.Client") as mock_cls:
        inst = MagicMock()
        inst.request.return_value = _ok({"id": "ord1", "status": "new"})
        mock_cls.return_value = inst
        client = AlpacaBrokerClient(api_key="k", secret_key="s", paper=True)
        client.submit_limit_order("AAPL240101C00190000", qty=1, side="buy", limit_price=2.50)

    inst.request.assert_called_once()
    call_kwargs = inst.request.call_args
    assert call_kwargs[0][0] == "POST"
    assert "/v2/orders" in call_kwargs[0][1]


def test_submit_limit_order_payload():
    with patch("app.execution.alpaca_broker.httpx.Client") as mock_cls:
        inst = MagicMock()
        inst.request.return_value = _ok({"id": "x"})
        mock_cls.return_value = inst
        client = AlpacaBrokerClient(api_key="k", secret_key="s")
        client.submit_limit_order("SYM", qty=1, side="buy", limit_price=3.75)

    payload = inst.request.call_args[1]["json"]
    assert payload["symbol"] == "SYM"
    assert payload["qty"] == "1"
    assert payload["side"] == "buy"
    assert payload["type"] == "limit"
    assert payload["time_in_force"] == "day"
    assert payload["limit_price"] == "3.75"


def test_submit_limit_order_returns_response_dict():
    with patch("app.execution.alpaca_broker.httpx.Client") as mock_cls:
        inst = MagicMock()
        inst.request.return_value = _ok({"id": "ord42", "status": "new"})
        mock_cls.return_value = inst
        client = AlpacaBrokerClient(api_key="k", secret_key="s")
        result = client.submit_limit_order("X", qty=1, side="buy", limit_price=1.0)

    assert result["id"] == "ord42"


def test_submit_limit_order_raises_on_error():
    with patch("app.execution.alpaca_broker.httpx.Client") as mock_cls:
        inst = MagicMock()
        inst.request.return_value = _err(403)
        mock_cls.return_value = inst
        client = AlpacaBrokerClient(api_key="k", secret_key="s")
        with pytest.raises(AlpacaBrokerError) as exc_info:
            client.submit_limit_order("X", qty=1, side="buy", limit_price=1.0)

    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# get_order
# ---------------------------------------------------------------------------


def test_get_order_calls_correct_path():
    with patch("app.execution.alpaca_broker.httpx.Client") as mock_cls:
        inst = MagicMock()
        inst.request.return_value = _ok({"id": "ord1", "status": "filled"})
        mock_cls.return_value = inst
        client = AlpacaBrokerClient(api_key="k", secret_key="s")
        result = client.get_order("ord1")

    assert result["status"] == "filled"
    call = inst.request.call_args
    assert call[0][0] == "GET"
    assert "/v2/orders/ord1" in call[0][1]


def test_get_order_raises_on_error():
    with patch("app.execution.alpaca_broker.httpx.Client") as mock_cls:
        inst = MagicMock()
        inst.request.return_value = _err(404)
        mock_cls.return_value = inst
        client = AlpacaBrokerClient(api_key="k", secret_key="s")
        with pytest.raises(AlpacaBrokerError):
            client.get_order("missing")


# ---------------------------------------------------------------------------
# cancel_order
# ---------------------------------------------------------------------------


def test_cancel_order_sends_delete():
    with patch("app.execution.alpaca_broker.httpx.Client") as mock_cls:
        inst = MagicMock()
        del_resp = MagicMock()
        del_resp.status_code = 204
        inst.delete.return_value = del_resp
        mock_cls.return_value = inst
        client = AlpacaBrokerClient(api_key="k", secret_key="s")
        client.cancel_order("ord1")

    inst.delete.assert_called_once_with("/v2/orders/ord1")


def test_cancel_order_ignores_404():
    with patch("app.execution.alpaca_broker.httpx.Client") as mock_cls:
        inst = MagicMock()
        del_resp = MagicMock()
        del_resp.status_code = 404
        inst.delete.return_value = del_resp
        mock_cls.return_value = inst
        client = AlpacaBrokerClient(api_key="k", secret_key="s")
        client.cancel_order("gone")  # should not raise


def test_cancel_order_raises_on_unexpected_error():
    with patch("app.execution.alpaca_broker.httpx.Client") as mock_cls:
        inst = MagicMock()
        del_resp = MagicMock()
        del_resp.status_code = 500
        del_resp.text = "server error"
        inst.delete.return_value = del_resp
        mock_cls.return_value = inst
        client = AlpacaBrokerClient(api_key="k", secret_key="s")
        with pytest.raises(AlpacaBrokerError):
            client.cancel_order("ord1")
