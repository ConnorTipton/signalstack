"""Alpaca paper trading broker client.

Thin synchronous wrapper around the Alpaca trading REST API.
Defaults to the paper endpoint; flip `paper=False` only for live (never in V1).
"""

from __future__ import annotations

import httpx

_PAPER_URL = "https://paper-api.alpaca.markets"
_LIVE_URL = "https://api.alpaca.markets"
_TIMEOUT = 10.0


class AlpacaBrokerError(Exception):
    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        super().__init__(f"Alpaca broker {status_code}: {body[:200]}")


class AlpacaBrokerClient:
    """Synchronous Alpaca broker client for paper order management.

    Parameters
    ----------
    api_key / secret_key:
        Alpaca credentials. Use paper-account keys when ``paper=True``.
    paper:
        If True (default), routes requests to the paper endpoint.
    """

    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        paper: bool = True,
        http_client: httpx.Client | None = None,
    ) -> None:
        base_url = _PAPER_URL if paper else _LIVE_URL
        self._own_client = http_client is None
        self._http = http_client or httpx.Client(
            base_url=base_url,
            headers={
                "APCA-API-KEY-ID": api_key,
                "APCA-API-SECRET-KEY": secret_key,
            },
            timeout=_TIMEOUT,
        )

    def close(self) -> None:
        if self._own_client:
            self._http.close()

    def __enter__(self) -> AlpacaBrokerClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def _request(self, method: str, path: str, **kwargs: object) -> dict:
        resp = self._http.request(method, path, **kwargs)
        if not resp.is_success:
            raise AlpacaBrokerError(resp.status_code, resp.text)
        return resp.json()

    def submit_limit_order(
        self,
        symbol: str,
        qty: int,
        side: str,
        limit_price: float,
    ) -> dict:
        """Submit a day limit order. Returns raw Alpaca order dict."""
        return self._request(
            "POST",
            "/v2/orders",
            json={
                "symbol": symbol,
                "qty": str(qty),
                "side": side,
                "type": "limit",
                "time_in_force": "day",
                "limit_price": str(round(limit_price, 2)),
            },
        )

    def get_order(self, order_id: str) -> dict:
        """Fetch current state of an order."""
        return self._request("GET", f"/v2/orders/{order_id}")

    def cancel_order(self, order_id: str) -> None:
        """Cancel an open order. Ignores 404 (already gone)."""
        resp = self._http.delete(f"/v2/orders/{order_id}")
        if resp.status_code not in (200, 204, 404):
            raise AlpacaBrokerError(resp.status_code, resp.text)
