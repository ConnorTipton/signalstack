"""Unit tests for NewsDetector (Detector A).

All tests use mocked DB sessions and stub out the fetch methods so no live
database is required.
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from app.db.models.news import LlmNewsLabel, NewsArticle, NewsArticleTicker
from app.db.models.signals import DetectedEvent
from app.signals.news import NewsDetector

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _label(
    id: int = 1,
    article_id: int = 10,
    event_type: str | None = "earnings_beat",
    polarity: str = "positive",
    importance: float = 0.9,
    confidence: float = 0.85,
    summary: str = "Beat estimates by 20%.",
) -> MagicMock:
    lbl = MagicMock(spec=LlmNewsLabel)
    lbl.id = id
    lbl.article_id = article_id
    lbl.event_type = event_type
    lbl.polarity = polarity
    lbl.importance = importance
    lbl.confidence = confidence
    lbl.one_sentence_summary = summary
    return lbl


def _article(source_tier: int = 1) -> MagicMock:
    art = MagicMock(spec=NewsArticle)
    art.source_tier = source_tier
    return art


def _ticker(ticker: str, symbol_id: int) -> MagicMock:
    tr = MagicMock(spec=NewsArticleTicker)
    tr.ticker = ticker
    tr.symbol_id = symbol_id
    return tr


def _db(article: MagicMock | None = None) -> MagicMock:
    db = MagicMock()
    db.get.return_value = article or _article()
    db.commit = MagicMock()
    db.add = MagicMock()
    return db


# ---------------------------------------------------------------------------
# _is_usable
# ---------------------------------------------------------------------------


def test_is_usable_true_when_event_type_set():
    lbl = _label(event_type="earnings_beat")
    assert NewsDetector._is_usable(lbl) is True


def test_is_usable_false_when_event_type_none():
    lbl = _label(event_type=None)
    assert NewsDetector._is_usable(lbl) is False


# ---------------------------------------------------------------------------
# _build_event
# ---------------------------------------------------------------------------


def test_build_event_maps_all_fields():
    lbl = _label(
        id=7,
        article_id=99,
        event_type="guidance_raise",
        polarity="positive",
        importance=0.8,
        confidence=0.75,
        summary="Raised full-year guidance.",
    )
    art = _article(source_tier=2)
    tr = _ticker("MSFT", symbol_id=3)

    evt = NewsDetector._build_event(lbl, art, tr)

    assert evt.detector == "A"
    assert evt.ticker == "MSFT"
    assert evt.symbol_id == 3
    assert evt.event_type == "guidance_raise"
    assert evt.polarity == "positive"
    assert pytest.approx(evt.importance) == 0.8
    assert pytest.approx(evt.confidence) == 0.75
    assert evt.source_tier == 2
    assert evt.one_sentence_summary == "Raised full-year guidance."
    assert evt.news_article_id == 99
    assert evt.llm_label_id == 7


def test_build_event_handles_none_article():
    lbl = _label()
    tr = _ticker("AAPL", symbol_id=1)
    evt = NewsDetector._build_event(lbl, None, tr)
    assert evt.source_tier is None


def test_build_event_handles_none_ticker_symbol_id():
    lbl = _label()
    tr = _ticker("SPY", symbol_id=None)
    evt = NewsDetector._build_event(lbl, _article(), tr)
    assert evt.symbol_id == 0


def test_build_event_handles_none_importance_and_confidence():
    lbl = _label(importance=None, confidence=None)
    tr = _ticker("AAPL", symbol_id=1)
    evt = NewsDetector._build_event(lbl, _article(), tr)
    assert evt.importance is None
    assert evt.confidence is None


# ---------------------------------------------------------------------------
# run_once — control flow
# ---------------------------------------------------------------------------


def test_run_once_skips_label_with_no_event_type():
    detector = NewsDetector()
    detector._fetch_undetected = lambda db, **kw: [_label(event_type=None)]

    db = _db()
    count = detector.run_once(db)

    assert count == 0
    db.add.assert_not_called()
    db.commit.assert_called_once()


def test_run_once_skips_label_with_no_tickers():
    detector = NewsDetector()
    detector._fetch_undetected = lambda db, **kw: [_label()]
    detector._fetch_tickers = lambda db, article_id: []

    db = _db()
    count = detector.run_once(db)

    assert count == 0
    db.add.assert_not_called()


def test_run_once_emits_one_event_per_ticker():
    tickers = [_ticker("AAPL", 1), _ticker("SPY", 2)]
    detector = NewsDetector()
    detector._fetch_undetected = lambda db, **kw: [_label()]
    detector._fetch_tickers = lambda db, article_id: tickers

    db = _db()
    count = detector.run_once(db)

    assert count == 2
    assert db.add.call_count == 2


def test_run_once_emits_events_for_multiple_labels():
    labels = [_label(id=1, article_id=10), _label(id=2, article_id=11)]
    tickers = [_ticker("AAPL", 1)]

    detector = NewsDetector()
    detector._fetch_undetected = lambda db, **kw: labels
    detector._fetch_tickers = lambda db, article_id: tickers

    db = _db()
    count = detector.run_once(db)

    assert count == 2
    assert db.add.call_count == 2


def test_run_once_returns_zero_when_no_labels():
    detector = NewsDetector()
    detector._fetch_undetected = lambda db, **kw: []

    db = _db()
    count = detector.run_once(db)

    assert count == 0


def test_run_once_emitted_events_are_detector_a():
    detector = NewsDetector()
    detector._fetch_undetected = lambda db, **kw: [_label()]
    detector._fetch_tickers = lambda db, article_id: [_ticker("AAPL", 1)]

    db = _db()
    detector.run_once(db)

    added_event: DetectedEvent = db.add.call_args[0][0]
    assert added_event.detector == "A"


def test_run_once_event_ticker_matches_ticker_row():
    detector = NewsDetector()
    detector._fetch_undetected = lambda db, **kw: [_label()]
    detector._fetch_tickers = lambda db, article_id: [_ticker("NVDA", 5)]

    db = _db()
    detector.run_once(db)

    added_event: DetectedEvent = db.add.call_args[0][0]
    assert added_event.ticker == "NVDA"
    assert added_event.symbol_id == 5


# ---------------------------------------------------------------------------
# NewsDetectorWorker — async control flow
# ---------------------------------------------------------------------------


async def test_worker_run_cancels_cleanly():
    from app.signals.news import NewsDetectorWorker

    detector = MagicMock()
    detector.run_once = MagicMock(return_value=0)

    worker = NewsDetectorWorker(detector=detector, interval_seconds=0.01)

    # Patch SessionLocal so no real DB is needed
    import app.signals.news as news_mod

    original = news_mod.SessionLocal

    class _FakeCtx:
        def __enter__(self):
            return MagicMock()

        def __exit__(self, *_):
            pass

    news_mod.SessionLocal = _FakeCtx  # type: ignore[assignment]
    try:
        task = asyncio.create_task(worker.run())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        news_mod.SessionLocal = original
