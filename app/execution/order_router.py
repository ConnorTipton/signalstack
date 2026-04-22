"""Order router — converts sent Alert rows into PaperOrder rows.

Rules enforced (§17):
- Limit orders only.
- One contract per order (qty=1).
- One open signal per symbol at a time (open position or pending order blocks routing).
- In dry_run mode no Alpaca API calls are made; status is set to "dry_run".
- If a broker client is provided and dry_run=False, the order is submitted to
  Alpaca immediately; status becomes "submitted" or "submit_failed".
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.execution import Alert, PaperOrder, PaperPosition
from app.db.models.market import OptionQuote

log = logging.getLogger(__name__)


def _fetch_ask_price(db: Session, contract_symbol: str) -> float | None:
    row = (
        db.query(OptionQuote)
        .filter(OptionQuote.contract_symbol == contract_symbol)
        .order_by(OptionQuote.quote_time.desc())
        .first()
    )
    return float(row.ask) if row and row.ask else None


def _has_open_position(db: Session, ticker: str) -> bool:
    return (
        db.query(PaperPosition)
        .filter(PaperPosition.ticker == ticker, PaperPosition.status == "open")
        .first()
    ) is not None


def _has_active_order(db: Session, ticker: str) -> bool:
    return (
        db.query(PaperOrder)
        .filter(
            PaperOrder.ticker == ticker,
            PaperOrder.status.in_(["pending", "submitted", "dry_run"]),
        )
        .first()
    ) is not None


class OrderRouter:
    """Routes promoted alerts to paper orders.

    Parameters
    ----------
    broker_client:
        AlpacaBrokerClient instance. If None, no orders are submitted to
        Alpaca regardless of dry_run.
    dry_run:
        If True (default), creates orders with status="dry_run" without
        calling Alpaca.
    """

    def __init__(
        self,
        broker_client=None,
        *,
        dry_run: bool = True,
    ) -> None:
        self._broker = broker_client
        self._dry_run = dry_run

    def route(self, alert: Alert, db: Session) -> PaperOrder | None:
        """Create a PaperOrder for this alert if no conflicting state exists.

        Returns the created PaperOrder, or None if skipped.
        """
        if not alert.contract_symbol:
            log.debug("OrderRouter: alert %s has no contract_symbol, skipping", alert.id)
            return None

        if _has_open_position(db, alert.ticker) or _has_active_order(db, alert.ticker):
            log.debug(
                "OrderRouter: position/order already active for %s, skipping", alert.ticker
            )
            return None

        limit_price = _fetch_ask_price(db, alert.contract_symbol)
        if limit_price is None:
            log.debug("OrderRouter: no ask price found for %s, order will not submit to Alpaca", alert.contract_symbol)

        order = PaperOrder(
            alert_id=alert.id,
            symbol_id=alert.symbol_id,
            ticker=alert.ticker,
            contract_symbol=alert.contract_symbol,
            option_type=alert.option_type or "call",
            strike=alert.strike,
            expiration_date=alert.expiration_date,
            side="buy",
            quantity=1,
            order_type="limit",
            limit_price=limit_price,
            status="dry_run" if self._dry_run else "pending",
        )

        if not self._dry_run and self._broker is not None and order.limit_price is not None:
            try:
                result = self._broker.submit_limit_order(
                    symbol=alert.contract_symbol,
                    qty=1,
                    side="buy",
                    limit_price=float(order.limit_price),
                )
                order.alpaca_order_id = result.get("id")
                order.status = "submitted"
                order.submitted_at = datetime.now(UTC)
            except Exception as exc:
                log.warning(
                    "OrderRouter: Alpaca submission failed for %s: %s", alert.ticker, exc
                )
                order.status = "submit_failed"
                order.submitted_at = datetime.now(UTC)

        db.add(order)
        log.info(
            "OrderRouter: created %s PaperOrder for %s (%s)",
            order.status,
            alert.ticker,
            alert.contract_symbol,
        )
        return order
