"""Alert worker — polls promoted signal_candidates and sends Telegram alerts.

On each cycle:
  Phase A — find promoted signal_candidates that have a contract but no Alert
             row yet; build an Alert and attempt to send via Telegram.
  Phase B — retry Alert rows that failed in a previous cycle (send_attempts ≥ 1,
             sent_at IS NULL, send_attempts < max_retries).

If telegram_client is None, alerts are persisted and marked handled locally
so API/review and paper execution can still see them. dry_run=True prefixes messages with
"[DRY RUN]" so they are clearly labelled in chat.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.alerts.formatter import AlertFormatter
from app.alerts.telegram import TelegramClient
from app.core.desktop_state import read_sensitivity, sensitivity_mode_to_grades
from app.db.models.execution import Alert
from app.db.models.provider import ProviderHealth
from app.db.models.signals import DetectedEvent, SignalCandidate
from app.db.session import SessionLocal

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 10.0
_DEFAULT_BATCH = 50
_MAX_RETRIES = 3
_BACKOFF_BASE_SECONDS = 30
_CIRCUIT_OPEN_THRESHOLD = 5
_CIRCUIT_OPEN_SECONDS = 600


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
        self._consecutive_failures = 0
        self._circuit_open_until: datetime | None = None

    async def run(self) -> None:
        """Main loop: process alerts, sleep, repeat until cancelled."""
        self._last_success_at: datetime | None = None
        while True:
            t0 = datetime.now(UTC)
            try:
                count = await asyncio.to_thread(self._run_once_in_session)
                if count:
                    log.info("AlertWorker: created %d new alert(s)", count)
                self._last_success_at = datetime.now(UTC)
                await asyncio.to_thread(self._record_health)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("AlertWorker cycle error: %s", exc)
                await asyncio.to_thread(self._record_health, str(exc))
            elapsed = (datetime.now(UTC) - t0).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))

    def _record_health(self, error: str | None = None) -> None:
        telegram_configured = self._telegram is not None
        is_healthy = telegram_configured and self._consecutive_failures == 0
        confidence = 1.0 if is_healthy else max(0.0, 1.0 - 0.2 * self._consecutive_failures)
        with SessionLocal() as db:
            db.add(
                ProviderHealth(
                    checked_at=datetime.now(UTC),
                    provider_name="telegram",
                    is_healthy=is_healthy,
                    provider_confidence=round(confidence, 3),
                    last_success_at=self._last_success_at,
                    consecutive_failures=self._consecutive_failures,
                    error_message=error if error else (None if telegram_configured else "Telegram not configured"),
                )
            )
            db.commit()

    def _run_once_in_session(self) -> int:
        with SessionLocal() as db:
            return self.run_once(db)

    def run_once(self, db: Session) -> int:
        """Process new candidates and retry failed alerts.

        Returns the count of new Alert rows created (not retries).
        """
        now = datetime.now(UTC)

        # Phase A: new candidates → new Alert rows
        candidates = self._fetch_unalerted_candidates(db, batch_size=self._batch_size)
        new_alerts: list[Alert] = []

        # Sensitivity gate: only allowed grades produce alerts.
        # Rejected candidates are marked with status='rejected' and a
        # sensitivity_gate rejection_reason, so they are not re-fetched
        # next cycle. The grade itself is unchanged — the actual emitted
        # Alert (when admitted) carries the candidate's true grade.
        mode = read_sensitivity()
        allowed_grades = sensitivity_mode_to_grades(mode)

        for candidate in candidates:
            if candidate.grade not in allowed_grades:
                candidate.status = "rejected"
                candidate.rejection_reason = (
                    f"sensitivity_gate:{mode}:grade_{candidate.grade}"
                )
                candidate.rejected_at = now
                continue

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
            alert.sent_at = now
            log.debug(
                "AlertWorker: Telegram not configured, marking alert for %s as persisted",
                alert.ticker,
            )
            return

        if self._circuit_open_until is not None and now < self._circuit_open_until:
            log.warning(
                "AlertWorker: circuit open until %s — skipping send for %s",
                self._circuit_open_until.isoformat(),
                alert.ticker,
            )
            return

        try:
            text = AlertFormatter.render(alert)
            self._telegram.send_message(text)
            alert.sent_at = now
            alert.send_attempts = (alert.send_attempts or 0) + 1
            if self._consecutive_failures > 0:
                log.info("AlertWorker: circuit closed — Telegram healthy again")
            self._consecutive_failures = 0
            self._circuit_open_until = None
            log.info("AlertWorker: sent alert for %s (grade=%s)", alert.ticker, alert.grade)
        except Exception as exc:
            attempt = (alert.send_attempts or 0) + 1
            alert.send_attempts = attempt
            alert.last_error = str(exc)[:500]
            delay = _BACKOFF_BASE_SECONDS * (2 ** (attempt - 1))
            alert.next_retry_at = now + timedelta(seconds=delay)
            self._consecutive_failures += 1
            if self._consecutive_failures >= _CIRCUIT_OPEN_THRESHOLD:
                self._circuit_open_until = now + timedelta(seconds=_CIRCUIT_OPEN_SECONDS)
                log.error(
                    "AlertWorker: circuit opened after %d consecutive failures — "
                    "pausing Telegram sends for %ds",
                    self._consecutive_failures,
                    _CIRCUIT_OPEN_SECONDS,
                )
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
        """Return Alert rows that failed to send and whose backoff window has elapsed."""
        now = datetime.now(UTC)
        return (
            db.query(Alert)
            .filter(
                Alert.sent_at.is_(None),
                Alert.send_attempts >= 1,
                Alert.send_attempts < max_retries,
                or_(Alert.next_retry_at.is_(None), Alert.next_retry_at <= now),
            )
            .all()
        )

    @staticmethod
    def _fetch_news_summary(db: Session, news_event_id: int | None) -> str | None:
        if news_event_id is None:
            return None
        event = db.query(DetectedEvent).filter(DetectedEvent.id == news_event_id).first()
        return event.one_sentence_summary if event else None
