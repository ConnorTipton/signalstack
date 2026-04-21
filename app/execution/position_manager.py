"""Position manager — promotes fills to positions and monitors exit conditions.

On each call to ``process(db)``:
  Phase A — find PaperOrders with status="submitted"; poll Alpaca for fills;
             open a PaperPosition on fill or mark cancelled/expired.
  Phase B — find PaperOrders with status="dry_run" that have no PaperPosition
             yet; open a simulated position immediately (entry_price=0.0).
  Phase C — find open PaperPositions whose time_stop_at has passed; close them.

Target-price exits (target1, target2, invalidation) are placeholders for a
future phase that can supply real-time option quotes.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.execution import PaperOrder, PaperPosition, PositionEvent

log = logging.getLogger(__name__)


class PositionManager:
    """Manages the lifecycle of paper positions.

    Parameters
    ----------
    broker_client:
        AlpacaBrokerClient instance. Required for live order polling.
        If None, only dry_run position management runs.
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
            order.status = "filled"
            order.filled_at = datetime.now(UTC)
            order.fill_price = 0.0
            self._open_position(db, order, entry_price=0.0, dry_run=True)

    # ------------------------------------------------------------------
    # Phase C: close positions that have hit their time stop
    # ------------------------------------------------------------------

    def _check_exits(self, db: Session) -> None:
        now = datetime.now(UTC)
        open_positions = (
            db.query(PaperPosition).filter(PaperPosition.status == "open").all()
        )
        for pos in open_positions:
            if pos.time_stop_at and now >= pos.time_stop_at:
                self._close_position(
                    db, pos, exit_price=float(pos.entry_price or 0), reason="time_stop", now=now
                )

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
