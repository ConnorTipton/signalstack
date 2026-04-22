"""Position manager — promotes fills to positions and monitors exit conditions.

On each call to ``process(db)``:
  Phase A — find PaperOrders with status="submitted"; poll Alpaca for fills;
             open a PaperPosition on fill or mark cancelled/expired.
  Phase B — find PaperOrders with status="dry_run" that have no PaperPosition
             yet; open a simulated position using the current ask price.
  Phase C — find open PaperPositions; check time-stop and price-based exits;
             submit sell orders to Alpaca for live positions.

Exit logic:
  - time_stop_at parsed from alert.time_stop text on position open.
  - target1_price = 2× entry, invalidation_price = 0.5× entry.
  - Bid price from option_quotes used for price-based exit checks and sell orders.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.db.models.execution import Alert, PaperOrder, PaperPosition, PositionEvent
from app.db.models.market import OptionQuote

log = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")

# Exit thresholds relative to entry price
_INVALIDATION_MULT = 0.5   # close at 50% loss
_TARGET1_MULT = 2.0        # close at 2× gain
_TARGET2_MULT = 3.0        # informational 3× level


def _market_close_et(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, 16, 0, tzinfo=_ET).astimezone(UTC)


def _parse_time_stop(time_stop: str | None, expiration_date: date) -> datetime:
    """Convert alert.time_stop text to a UTC datetime.

    Recognises common patterns: "end of day", "N days", "N hours", "friday".
    Falls back to expiration-day market close if nothing matches.
    """
    if time_stop and isinstance(time_stop, str):
        text = time_stop.lower()
        now_et = datetime.now(_ET)
        if any(kw in text for kw in ("end of day", "eod", "close of market", "market close", "today")):
            return _market_close_et(now_et.date())
        if any(kw in text for kw in ("end of week", "end of the week", "friday", "this week")):
            days = (4 - now_et.weekday()) % 7 or 7
            return _market_close_et(now_et.date() + timedelta(days=days))
        m = re.search(r"(\d+)\s*day", text)
        if m:
            return _market_close_et(now_et.date() + timedelta(days=int(m.group(1))))
        m = re.search(r"(\d+)\s*hour", text)
        if m:
            return datetime.now(UTC) + timedelta(hours=int(m.group(1)))
    return _market_close_et(expiration_date)


def _fetch_option_quote(db: Session, contract_symbol: str) -> OptionQuote | None:
    return (
        db.query(OptionQuote)
        .filter(OptionQuote.contract_symbol == contract_symbol)
        .order_by(OptionQuote.quote_time.desc())
        .first()
    )


def _fetch_bid_price(db: Session, contract_symbol: str) -> float | None:
    row = _fetch_option_quote(db, contract_symbol)
    return float(row.bid) if row and row.bid else None


def _fetch_ask_price(db: Session, contract_symbol: str) -> float | None:
    row = _fetch_option_quote(db, contract_symbol)
    return float(row.ask) if row and row.ask else None


class PositionManager:
    """Manages the lifecycle of paper positions.

    Parameters
    ----------
    broker_client:
        AlpacaBrokerClient instance. Required for live order polling and sell
        order submission. If None, only dry_run position management runs.
    """

    def __init__(self, broker_client=None) -> None:
        self._broker = broker_client

    def process(self, db: Session) -> None:
        """Run one management cycle."""
        self._promote_fills(db)
        self._open_dry_run_positions(db)
        self._check_exits(db)

    # ------------------------------------------------------------------
    # Phase A: poll Alpaca for fills on submitted orders
    # ------------------------------------------------------------------

    def _promote_fills(self, db: Session) -> None:
        if self._broker is None:
            return

        submitted = (
            db.query(PaperOrder).filter(PaperOrder.status == "submitted").all()
        )
        for order in submitted:
            if not order.alpaca_order_id:
                continue
            try:
                raw = self._broker.get_order(order.alpaca_order_id)
                status = raw.get("status", "")
                if status == "filled":
                    fill_price = float(raw.get("filled_avg_price") or 0)
                    order.status = "filled"
                    order.filled_at = datetime.now(UTC)
                    order.fill_price = fill_price
                    self._open_position(db, order, entry_price=fill_price)
                elif status in ("cancelled", "expired"):
                    order.status = status
                    order.cancelled_at = datetime.now(UTC)
                    log.info(
                        "PositionManager: order %s %s", order.alpaca_order_id, status
                    )
            except Exception as exc:
                log.warning(
                    "PositionManager: poll failed for order %s: %s", order.id, exc
                )

    # ------------------------------------------------------------------
    # Phase B: immediately open simulated positions for dry_run orders
    # ------------------------------------------------------------------

    def _open_dry_run_positions(self, db: Session) -> None:
        dry_orders = (
            db.query(PaperOrder).filter(PaperOrder.status == "dry_run").all()
        )
        for order in dry_orders:
            existing = (
                db.query(PaperPosition)
                .filter(PaperPosition.order_id == order.id)
                .first()
            )
            if existing:
                continue
            ask = _fetch_ask_price(db, order.contract_symbol)
            entry_price = ask if ask is not None else 0.0
            order.status = "filled"
            order.filled_at = datetime.now(UTC)
            order.fill_price = entry_price
            self._open_position(db, order, entry_price=entry_price, dry_run=True)

    # ------------------------------------------------------------------
    # Phase C: check time-stop and price-based exits on open positions
    # ------------------------------------------------------------------

    def _check_exits(self, db: Session) -> None:
        now = datetime.now(UTC)
        open_positions = (
            db.query(PaperPosition).filter(PaperPosition.status == "open").all()
        )
        for pos in open_positions:
            if pos.time_stop_at and now >= pos.time_stop_at:
                bid = _fetch_bid_price(db, pos.contract_symbol)
                exit_price = bid if bid is not None else float(pos.entry_price or 0)
                self._submit_sell_order(db, pos, exit_price)
                self._close_position(db, pos, exit_price=exit_price, reason="time_stop", now=now)
                continue

            if not pos.entry_price:
                continue
            bid = _fetch_bid_price(db, pos.contract_symbol)
            if bid is None:
                continue
            if pos.invalidation_price is not None and bid <= float(pos.invalidation_price):
                self._submit_sell_order(db, pos, bid)
                self._close_position(db, pos, exit_price=bid, reason="invalidation", now=now)
            elif pos.target1_price is not None and bid >= float(pos.target1_price):
                self._submit_sell_order(db, pos, bid)
                self._close_position(db, pos, exit_price=bid, reason="target1", now=now)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _open_position(
        self,
        db: Session,
        order: PaperOrder,
        entry_price: float,
        *,
        dry_run: bool = False,
    ) -> PaperPosition:
        alert = db.get(Alert, order.alert_id) if order.alert_id else None
        time_stop_at = _parse_time_stop(
            alert.time_stop if alert else None,
            order.expiration_date,
        )
        target1 = round(entry_price * _TARGET1_MULT, 4) if entry_price else None
        target2 = round(entry_price * _TARGET2_MULT, 4) if entry_price else None
        invalidation = round(entry_price * _INVALIDATION_MULT, 4) if entry_price else None

        position = PaperPosition(
            order_id=order.id,
            alert_id=order.alert_id,
            symbol_id=order.symbol_id,
            ticker=order.ticker,
            contract_symbol=order.contract_symbol,
            option_type=order.option_type,
            strike=float(order.strike) if order.strike is not None else 0.0,
            expiration_date=order.expiration_date,
            quantity=order.quantity,
            entry_price=entry_price,
            status="open",
            time_stop_at=time_stop_at,
            target1_price=target1,
            target2_price=target2,
            invalidation_price=invalidation,
        )
        db.add(position)
        db.flush()

        event = PositionEvent(
            position_id=position.id,
            event_type="entry_dry_run" if dry_run else "entry",
            price_at_event=entry_price,
            notes=f"contract={order.contract_symbol}",
        )
        db.add(event)

        log.info(
            "PositionManager: opened position %s for %s at %.4f%s",
            position.id,
            order.ticker,
            entry_price,
            " [DRY RUN]" if dry_run else "",
        )
        return position

    def _submit_sell_order(
        self, db: Session, position: PaperPosition, limit_price: float
    ) -> None:
        """Submit a sell limit order to Alpaca for live (non-dry_run) positions."""
        if self._broker is None:
            return
        # Only sell positions backed by a real Alpaca buy
        if position.order_id:
            order = db.get(PaperOrder, position.order_id)
            if order is None or not order.alpaca_order_id:
                return
        try:
            self._broker.submit_limit_order(
                symbol=position.contract_symbol,
                qty=position.quantity,
                side="sell",
                limit_price=round(limit_price, 2),
            )
            log.info(
                "PositionManager: sell order submitted for %s at %.4f",
                position.ticker,
                limit_price,
            )
        except Exception as exc:
            log.warning(
                "PositionManager: sell order failed for %s: %s", position.ticker, exc
            )

    def _close_position(
        self,
        db: Session,
        position: PaperPosition,
        *,
        exit_price: float,
        reason: str,
        now: datetime,
    ) -> None:
        entry = float(position.entry_price) if position.entry_price else 0.0
        pnl = (exit_price - entry) * position.quantity * 100
        pnl_pct = ((exit_price - entry) / entry) if entry else 0.0

        position.status = "closed"
        position.exit_price = exit_price
        position.exit_reason = reason
        position.closed_at = now
        position.pnl = pnl
        position.pnl_pct = pnl_pct

        event = PositionEvent(
            position_id=position.id,
            event_type=f"exit_{reason}",
            price_at_event=exit_price,
            notes=f"pnl={pnl:.4f}",
        )
        db.add(event)

        log.info(
            "PositionManager: closed position %s for %s reason=%s pnl=%.4f",
            position.id,
            position.ticker,
            reason,
            pnl,
        )
