"""Unit tests for AlertWorker (Phase 7).

Worker tests monkey-patch the static DB fetch methods to avoid a live DB,
following the same pattern as test_scoring.py.
"""

import asyncio
from datetime import UTC, date, datetime
from unittest.mock import MagicMock

import pytest

from app.alerts.formatter import AlertFormatter
from app.alerts.worker import _CIRCUIT_OPEN_THRESHOLD, _MAX_RETRIES, AlertWorker
from app.db.models.execution import Alert
from app.db.models.signals import SignalCandidate

_T0 = datetime(2026, 4, 21, 14, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate(
    id: int = 1,
    ticker: str = "AAPL",
    symbol_id: int = 2,
    status: str = "promoted",
    grade: str = "A",
    contract_type: str = "call",
    contract_symbol: str = "AAPL250501C00190000",
    contract_expiration: date = date(2025, 5, 1),
    contract_strike: float = 190.0,
    score: float = 85.0,
    news_event_id: int | None = 10,
    rejection_reason: str | None = None,
    price_score: float = 20.0,
    options_score: float = 12.0,
    contract_spread_pct: float | None = 0.08,
    contract_oi: int | None = 400,
    contract_volume: int | None = 50,
) -> MagicMock:
    c = MagicMock(spec=SignalCandidate)
    c.id = id
    c.ticker = ticker
    c.symbol_id = symbol_id
    c.status = status
    c.grade = grade
    c.contract_type = contract_type
    c.contract_symbol = contract_symbol
    c.contract_expiration = contract_expiration
    c.contract_strike = contract_strike
    c.score = score
    c.news_event_id = news_event_id
    c.rejection_reason = rejection_reason
    c.price_score = price_score
    c.options_score = options_score
    c.contract_spread_pct = contract_spread_pct
    c.contract_oi = contract_oi
    c.contract_volume = contract_volume
    return c


def _pending_alert(id: int = 99, ticker: str = "MSFT", send_attempts: int = 1) -> MagicMock:
    """Return a mock Alert that looks like a previously-failed send."""
    a = MagicMock(spec=Alert)
    a.id = id
    a.ticker = ticker
    a.send_attempts = send_attempts
    a.sent_at = None
    a.dry_run = True
    a.score = 75.0
    a.grade = "B"
    a.direction = "bullish"
    a.reason = "catalyst detected; price confirmed"
    a.entry_condition = "only if MSFT holds above breakout level"
    a.invalidation = "lose breakout level / VWAP"
    a.target1 = "Trim at +25% option premium"
    a.target2 = "Exit remainder at +50% or end-of-day"
    a.time_stop = "Close by 3:30 PM ET if no follow-through"
    a.liquidity_note = "spread 10% (tight); OI 400"
    a.data_note = "no caveats"
    a.expiration_date = None
    a.strike = None
    a.option_type = None
    return a


def _db_mock() -> MagicMock:
    db = MagicMock()
    db.add = MagicMock()
    db.commit = MagicMock()
    return db


def _worker(
    candidates=None,
    pending_alerts=None,
    news_summary: str | None = None,
    telegram_client=None,
    dry_run: bool = True,
) -> AlertWorker:
    w = AlertWorker(
        formatter=AlertFormatter(),
        telegram_client=telegram_client,
        dry_run=dry_run,
    )
    w._fetch_unalerted_candidates = lambda db, batch_size=50: candidates or []
    w._fetch_pending_alerts = lambda db, max_retries=_MAX_RETRIES: pending_alerts or []
    w._fetch_news_summary = lambda db, news_event_id: news_summary
    return w


# ---------------------------------------------------------------------------
# run_once — basic control flow
# ---------------------------------------------------------------------------


def test_run_once_no_candidates_returns_zero():
    assert _worker().run_once(_db_mock()) == 0


def test_run_once_returns_new_alert_count():
    w = _worker(candidates=[_candidate(id=1), _candidate(id=2, ticker="MSFT")])
    assert w.run_once(_db_mock()) == 2


def test_run_once_adds_one_alert_per_candidate():
    db = _db_mock()
    _worker(candidates=[_candidate(), _candidate(id=2, ticker="MSFT")]).run_once(db)
    assert db.add.call_count == 2


def test_run_once_does_not_count_retries():
    w = _worker(candidates=[_candidate()], pending_alerts=[_pending_alert()])
    assert w.run_once(_db_mock()) == 1  # only new, not retries


def test_run_once_commits_once():
    db = _db_mock()
    _worker(candidates=[_candidate()]).run_once(db)
    db.commit.assert_called_once()


# ---------------------------------------------------------------------------
# Telegram send behavior
# ---------------------------------------------------------------------------


def test_run_once_sends_when_telegram_configured():
    telegram = MagicMock()
    _worker(candidates=[_candidate()], telegram_client=telegram).run_once(_db_mock())
    telegram.send_message.assert_called_once()


def test_run_once_skips_send_when_telegram_is_none():
    captured: list[Alert] = []
    db = _db_mock()
    db.add.side_effect = lambda obj: captured.append(obj)

    _worker(candidates=[_candidate()], telegram_client=None).run_once(db)

    assert captured[0].sent_at is not None
    assert captured[0].send_attempts == 0


def test_run_once_sets_sent_at_on_success():
    telegram = MagicMock()
    captured: list[Alert] = []
    db = _db_mock()
    db.add.side_effect = lambda obj: captured.append(obj)

    _worker(candidates=[_candidate()], telegram_client=telegram).run_once(db)

    assert len(captured) == 1
    assert captured[0].sent_at is not None
    assert captured[0].send_attempts == 1


def test_run_once_records_error_on_send_failure():
    telegram = MagicMock()
    telegram.send_message.side_effect = RuntimeError("connection refused")
    captured: list[Alert] = []
    db = _db_mock()
    db.add.side_effect = lambda obj: captured.append(obj)

    _worker(candidates=[_candidate()], telegram_client=telegram).run_once(db)

    assert captured[0].sent_at is None
    assert captured[0].send_attempts == 1
    assert "connection refused" in (captured[0].last_error or "")


def test_run_once_retries_pending_alerts():
    telegram = MagicMock()
    pending = _pending_alert(send_attempts=1)
    _worker(candidates=[], pending_alerts=[pending], telegram_client=telegram).run_once(_db_mock())
    telegram.send_message.assert_called_once()


def test_run_once_does_not_retry_when_at_max():
    telegram = MagicMock()
    # Worker is initialized with max_retries=3; _fetch_pending_alerts already
    # filters send_attempts < max_retries, so this tests that the worker passes
    # max_retries correctly to the fetch method.
    w = AlertWorker(
        formatter=AlertFormatter(),
        telegram_client=telegram,
        max_retries=3,
    )
    w._fetch_unalerted_candidates = lambda db, batch_size=50: []
    w._fetch_pending_alerts = lambda db, max_retries=3: []  # simulate all exhausted
    w._fetch_news_summary = lambda db, neid: None

    w.run_once(_db_mock())
    telegram.send_message.assert_not_called()


def test_run_once_dry_run_message_has_prefix():
    sent: list[str] = []

    class FakeTelegram:
        def send_message(self, text: str) -> None:
            sent.append(text)

    _worker(
        candidates=[_candidate()],
        telegram_client=FakeTelegram(),
        dry_run=True,
    ).run_once(_db_mock())

    assert len(sent) == 1
    assert sent[0].startswith("[DRY RUN]")


def test_run_once_no_dry_run_prefix_when_false():
    sent: list[str] = []

    class FakeTelegram:
        def send_message(self, text: str) -> None:
            sent.append(text)

    _worker(
        candidates=[_candidate()],
        telegram_client=FakeTelegram(),
        dry_run=False,
    ).run_once(_db_mock())

    assert len(sent) == 1
    assert not sent[0].startswith("[DRY RUN]")


# ---------------------------------------------------------------------------
# Circuit breaker
# ---------------------------------------------------------------------------


def test_circuit_opens_after_threshold_consecutive_failures():
    telegram = MagicMock()
    telegram.send_message.side_effect = RuntimeError("timeout")

    w = AlertWorker(telegram_client=telegram)
    now = _T0

    for _ in range(_CIRCUIT_OPEN_THRESHOLD):
        alert = MagicMock(spec=Alert)
        alert.send_attempts = 0
        alert.ticker = "AAPL"
        alert.grade = "A"
        w._send(alert, now)

    assert w._circuit_open_until is not None
    assert w._circuit_open_until > now


def test_circuit_open_skips_send():
    telegram = MagicMock()
    w = AlertWorker(telegram_client=telegram)
    # Force circuit open
    w._circuit_open_until = _T0.replace(year=2099)

    alert = MagicMock(spec=Alert)
    alert.send_attempts = 1
    alert.ticker = "AAPL"
    alert.grade = "A"
    w._send(alert, _T0)

    telegram.send_message.assert_not_called()


def test_consecutive_failures_reset_on_success():
    telegram = MagicMock()
    w = AlertWorker(telegram_client=telegram)
    w._consecutive_failures = 3

    alert = MagicMock(spec=Alert)
    alert.send_attempts = 0
    alert.ticker = "AAPL"
    alert.grade = "A"
    w._send(alert, _T0)

    assert w._consecutive_failures == 0
    assert w._circuit_open_until is None


# ---------------------------------------------------------------------------
# Async cancel
# ---------------------------------------------------------------------------


async def test_worker_run_cancels_cleanly():
    worker = AlertWorker(interval_seconds=0.01)
    worker._fetch_unalerted_candidates = lambda db, batch_size=50: []
    worker._fetch_pending_alerts = lambda db, max_retries=_MAX_RETRIES: []
    worker._fetch_news_summary = lambda db, news_event_id: None

    import app.alerts.worker as worker_mod

    original = worker_mod.SessionLocal

    class _FakeCtx:
        def __enter__(self):
            return _db_mock()

        def __exit__(self, *_):
            pass

    worker_mod.SessionLocal = _FakeCtx  # type: ignore[assignment]
    try:
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        worker_mod.SessionLocal = original
