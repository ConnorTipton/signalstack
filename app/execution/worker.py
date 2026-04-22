"""Execution worker — routes alerts to paper orders and manages positions.

On each cycle (``run_once``):
  1. Find sent Alerts that have no PaperOrder yet → route via OrderRouter.
  2. Run PositionManager to promote fills and check exit conditions.

Wiring example (in an entrypoint or main loop):

    from app.execution.alpaca_broker import AlpacaBrokerClient
    from app.execution.order_router import OrderRouter
    from app.execution.position_manager import PositionManager
    from app.execution.worker import ExecutionWorker

    broker = AlpacaBrokerClient(api_key=..., secret_key=..., paper=True)
    worker = ExecutionWorker(
        order_router=OrderRouter(broker_client=broker, dry_run=False),
        position_manager=PositionManager(broker_client=broker),
        dry_run=False,
    )
    asyncio.run(worker.run())
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.execution import Alert, PaperOrder
from app.db.session import SessionLocal
from app.execution.order_router import OrderRouter
from app.execution.position_manager import PositionManager

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 30.0


class ExecutionWorker:
    """Async loop that routes alerts to paper orders and manages positions.

    Parameters
    ----------
    order_router:
        OrderRouter instance. Defaults to dry_run=True with no broker.
    position_manager:
        PositionManager instance. Defaults to no broker.
    interval_seconds:
        Seconds between cycles. Default 30.
    dry_run:
        Passed to a default OrderRouter when order_router is None. Ignored
        if order_router is supplied explicitly.
    """

    def __init__(
        self,
        order_router: OrderRouter | None = None,
        position_manager: PositionManager | None = None,
        *,
        interval_seconds: float = _DEFAULT_INTERVAL,
        dry_run: bool = True,
    ) -> None:
        self._router = order_router or OrderRouter(dry_run=dry_run)
        self._pm = position_manager or PositionManager()
        self._interval = interval_seconds

    async def run(self) -> None:
        """Main loop: process execution, sleep, repeat until cancelled."""
        while True:
            t0 = datetime.now(UTC)
            try:
                with SessionLocal() as db:
                    count = self.run_once(db)
                if count:
                    log.info("ExecutionWorker: routed %d new order(s)", count)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("ExecutionWorker cycle error: %s", exc)
            elapsed = (datetime.now(UTC) - t0).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))

    def run_once(self, db: Session) -> int:
        """Route unrouted alerts and process positions.

        Returns the count of new PaperOrders created.
        """
        unrouted = self._fetch_unrouted_alerts(db)
        new_orders = 0
        for alert in unrouted:
            order = self._router.route(alert, db)
            if order is not None:
                new_orders += 1

        self._pm.process(db)
        db.commit()
        return new_orders

    # ------------------------------------------------------------------
    # DB queries — override in tests to avoid a live session
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_unrouted_alerts(db: Session) -> list[Alert]:
        """Return sent Alerts that have no PaperOrder yet."""
        already_routed = db.query(PaperOrder).filter(PaperOrder.alert_id == Alert.id).exists()
        return (
            db.query(Alert)
            .filter(
                Alert.sent_at.isnot(None),
                Alert.contract_symbol.isnot(None),
                ~already_routed,
            )
            .order_by(Alert.created_at)
            .all()
        )
