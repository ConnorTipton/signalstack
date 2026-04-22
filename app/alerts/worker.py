"""Alert worker — polls promoted signal_candidates and sends Telegram alerts.

On each cycle:
  Phase A — find promoted signal_candidates that have a contract but no Alert
             row yet; build an Alert and attempt to send via Telegram.
  Phase B — retry Alert rows that failed in a previous cycle (send_attempts ≥ 1,
             sent_at IS NULL, send_attempts < max_retries).

If telegram_client is None, alerts are persisted in the DB but sends are
skipped silently.  dry_run=True (the default) prefixes messages with
"[DRY RUN]" so they are clearly labelled in chat.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.alerts.formatter import AlertFormatter
from app.alerts.telegram import TelegramClient
from app.db.models.execution import Alert
from app.db.models.signals import DetectedEvent, SignalCandidate
from app.db.session import SessionLocal

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 30.0
_DEFAULT_BATCH = 50
_MAX_RETRIES = 3


class AlertWorker:
    """Async loop that formats and sends Telegram alerts for promoted signals.

    Parameters
    ----------
    formatter:
        AlertFormatter instance. Defaults to a plain AlertFormatter().
    telegram_client:
        TelegramClient instance. If None, sends are skipped (alerts are still
        persisted in the DB).
    interval_seconds:
        Seconds between cycles. Default 30.
    batch_size:
        Max new signal_candidates to process per cycle. Default 50.
    max_retries:
        Maximum send attempts before an alert is abandoned. Default 3.
    dry_run:
        If True (default), marks alerts as dry-run and prefixes messages with
        "[DRY RUN]".
    """

    def __init__(
        self,
        formatter: AlertFormatter | None = None,
        telegram_client: TelegramClient | None = None,
        *,
        interval_seconds: float = _DEFAULT_INTERVAL,
        batch_size: int = _DEFAULT_BATCH,
        max_retries: int = _MAX_RETRIES,
        dry_run: bool = True,
    ) -> None:
        self._formatter = formatter or AlertFormatter()
        self._telegram = telegram_client
        self._interval = interval_seconds
        self._batch_size = batch_size
        self._max_retries = max_retries
        self._dry_run = dry_run

    async def run(self) -> None:
        """Main loop: process alerts, sleep, repeat until cancelled."""
        while True:
            t0 = datetime.now(UTC)
            try:
                with SessionLocal() as db:
                    count = self.run_once(db)
                if count:
                    log.info("AlertWorker: created %d new alert(s)", count)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("AlertWorker cycle error: %s", exc)
            elapsed = (datetime.now(UTC) - t0).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))

    def run_once(self, db: Session) -> int:
        """Process new candidates and retry failed alerts.

        Returns the count of new Alert rows created (not retries).
        """
        now = datetime.now(UTC)

        # Phase A: new candidates → new Alert rows
        candidates = self._fetch_unalerted_candidates(db, batch_size=self._batch_size)
        new_alerts: list[Alert] = []
        for candidate in candidates:
            news_summary = self._fetch_news_summary(db, candidate.news_event_id)
            alert = self._formatter.build(
                candidate, news_summary=news_summary, dry_run=self._dry_run
            )
            db.add(alert)
            new_alerts.append(alert)

        # Phase B: retry alerts that failed in previous cycles (send_attempts ≥ 1)
        retry_alerts = self._fetch_pending_alerts(db, max_retries=self._max_retries)

        for alert in new_alerts + retry_alerts:
            self._send(alert, now)

        db.commit()
        return len(new_alerts)

    def _send(self, alert: Alert, now: datetime) -> None:
        """Attempt to send one alert via Telegram; update send state in-place."""
        if self._telegram is None:
            log.debug("AlertWorker: Telegram not configured, skipping send for %s", alert.ticker)
            return
        try:
            text = AlertFormatter.render(alert)
            self._telegram.send_message(text)
            alert.sent_at = now
            alert.send_attempts = (alert.send_attempts or 0) + 1
            log.info("AlertWorker: sent alert for %s (grade=%s)", alert.ticker, alert.grade)
        except Exception as exc:
            alert.send_attempts = (alert.send_attempts or 0) + 1
            alert.last_error = str(exc)[:500]
            log.warning("AlertWorker: send failed for %s: %s", alert.ticker, exc)

    # ------------------------------------------------------------------
    # DB queries — override in tests to avoid a live session
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_unalerted_candidates(
        db: Session,
        batch_size: int = _DEFAULT_BATCH,
    ) -> list[SignalCandidate]:
        """Return promoted+contracted candidates with no Alert row yet."""
        already_alerted = (
            db.query(Alert).filter(Alert.signal_candidate_id == SignalCandidate.id).exists()
        )
        return (
            db.query(SignalCandidate)
            .filter(
                SignalCandidate.status == "promoted",
                SignalCandidate.contract_symbol.isnot(None),
                ~already_alerted,
            )
            .order_by(SignalCandidate.created_at)
            .limit(batch_size)
            .all()
        )

    @staticmethod
    def _fetch_pending_alerts(
        db: Session,
        max_retries: int = _MAX_RETRIES,
    ) -> list[Alert]:
        """Return Alert rows that failed to send and are eligible for retry."""
        return (
            db.query(Alert)
            .filter(
                Alert.sent_at.is_(None),
                Alert.send_attempts >= 1,
                Alert.send_attempts < max_retries,
            )
            .all()
        )

    @staticmethod
    def _fetch_news_summary(db: Session, news_event_id: int | None) -> str | None:
        if news_event_id is None:
            return None
        event = db.query(DetectedEvent).filter(DetectedEvent.id == news_event_id).first()
        return event.one_sentence_summary if event else None
