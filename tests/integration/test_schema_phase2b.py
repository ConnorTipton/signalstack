"""Smoke tests: one INSERT per Phase 2b table."""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models.execution import Alert, DailyMetric, PaperOrder, PaperPosition, PositionEvent
from app.db.models.news import LlmNewsLabel, NewsArticle, NewsArticleTicker
from app.db.models.raw_events import (
    RawAlpacaMarketEvent,
    RawMarketauxEvent,
    RawNewsBackupEvent,
    RawOfficialNewsEvent,
    RawTradierEvent,
)
from app.db.models.signals import DetectedEvent, SignalCandidate
from app.db.models.symbols import Symbol

pytestmark = pytest.mark.usefixtures("db_engine")


def _add_symbol(db_session, ticker: str = "AAPL") -> int:
    sym = Symbol(ticker=ticker, name=f"{ticker} Inc.")
    db_session.add(sym)
    db_session.flush()
    return sym.id


NOW = datetime(2026, 4, 20, 14, 30, 0, tzinfo=UTC)
TODAY = date(2026, 4, 20)
EXPIRY = date(2026, 4, 25)


def _assert_duplicate_rejected(db_session, row) -> None:
    with pytest.raises(IntegrityError), db_session.begin_nested():
        db_session.add(row)
        db_session.flush()


# --- News tables ---


def test_news_article_insert(db_session):
    article = NewsArticle(
        source_name="edgar",
        source_tier=1,
        title="AAPL files 8-K",
        provider_event_id="edgar-001",
    )
    db_session.add(article)
    db_session.flush()
    assert article.id is not None


def test_news_article_ticker_insert(db_session):
    article = NewsArticle(source_name="edgar", source_tier=1, title="Test headline")
    db_session.add(article)
    db_session.flush()

    ticker = NewsArticleTicker(article_id=article.id, ticker="AAPL", symbol_id=4)
    db_session.add(ticker)
    db_session.flush()
    assert ticker.id is not None


def test_llm_news_label_insert(db_session):
    article = NewsArticle(source_name="edgar", source_tier=1, title="Test headline")
    db_session.add(article)
    db_session.flush()

    label = LlmNewsLabel(
        article_id=article.id,
        model_name="llama3.1:8b",
        prompt_text="Classify this headline.",
        response_text='{"polarity": "bullish"}',
        event_type="earnings",
        polarity="bullish",
        importance=0.8,
        confidence=0.9,
    )
    db_session.add(label)
    db_session.flush()
    assert label.id is not None


def test_llm_news_label_unique_per_article_and_model(db_session):
    article = NewsArticle(source_name="edgar", source_tier=1, title="Test headline")
    db_session.add(article)
    db_session.flush()

    db_session.add(
        LlmNewsLabel(
            article_id=article.id,
            model_name="claude-test",
            prompt_text="Classify this headline.",
            response_text="{}",
        )
    )
    db_session.flush()

    _assert_duplicate_rejected(
        db_session,
        LlmNewsLabel(
            article_id=article.id,
            model_name="claude-test",
            prompt_text="Classify this headline again.",
            response_text="{}",
        ),
    )


# --- Signal tables ---


def test_detected_event_insert(db_session):
    sid = _add_symbol(db_session)
    event = DetectedEvent(
        detector="A",
        symbol_id=sid,
        ticker="AAPL",
        event_type="earnings",
        polarity="positive",
        importance=0.8,
        confidence=0.9,
        source_tier=1,
    )
    db_session.add(event)
    db_session.flush()
    assert event.id is not None


def test_detected_event_unique_per_detector_article_symbol(db_session):
    sid = _add_symbol(db_session)
    article = NewsArticle(source_name="edgar", source_tier=1, title="Test headline")
    db_session.add(article)
    db_session.flush()

    db_session.add(
        DetectedEvent(
            detector="A",
            symbol_id=sid,
            ticker="AAPL",
            event_type="earnings",
            news_article_id=article.id,
        )
    )
    db_session.flush()

    _assert_duplicate_rejected(
        db_session,
        DetectedEvent(
            detector="A",
            symbol_id=sid,
            ticker="AAPL",
            event_type="guidance",
            news_article_id=article.id,
        ),
    )


def test_signal_candidate_insert(db_session):
    sid = _add_symbol(db_session)
    candidate = SignalCandidate(
        symbol_id=sid,
        ticker="AAPL",
        score=83.5,
        news_score=30.0,
        price_score=28.0,
        options_score=18.0,
        liquidity_score=9.0,
        data_confidence_score=5.0,
        grade="A-",
        status="promoted",
    )
    db_session.add(candidate)
    db_session.flush()
    assert candidate.id is not None


def test_signal_candidate_unique_per_news_event(db_session):
    sid = _add_symbol(db_session)
    event = DetectedEvent(detector="A", symbol_id=sid, ticker="AAPL")
    db_session.add(event)
    db_session.flush()

    db_session.add(
        SignalCandidate(
            symbol_id=sid,
            ticker="AAPL",
            news_event_id=event.id,
            status="promoted",
        )
    )
    db_session.flush()

    _assert_duplicate_rejected(
        db_session,
        SignalCandidate(
            symbol_id=sid,
            ticker="AAPL",
            news_event_id=event.id,
            status="promoted",
        ),
    )


# --- Execution tables ---


def test_alert_insert(db_session):
    sid = _add_symbol(db_session)
    alert = Alert(
        symbol_id=sid,
        ticker="AAPL",
        direction="bullish",
        score=83.5,
        grade="A-",
        contract_symbol="AAPL260425C00200000",
        expiration_date=EXPIRY,
        strike=200.0,
        option_type="call",
        dry_run=True,
    )
    db_session.add(alert)
    db_session.flush()
    assert alert.id is not None


def test_alert_unique_per_signal_candidate(db_session):
    sid = _add_symbol(db_session)
    candidate = SignalCandidate(symbol_id=sid, ticker="AAPL", status="promoted")
    db_session.add(candidate)
    db_session.flush()

    db_session.add(
        Alert(
            signal_candidate_id=candidate.id,
            symbol_id=sid,
            ticker="AAPL",
            direction="bullish",
            score=83.5,
        )
    )
    db_session.flush()

    _assert_duplicate_rejected(
        db_session,
        Alert(
            signal_candidate_id=candidate.id,
            symbol_id=sid,
            ticker="AAPL",
            direction="bullish",
            score=83.5,
        ),
    )


def test_paper_order_insert(db_session):
    sid = _add_symbol(db_session)
    order = PaperOrder(
        symbol_id=sid,
        ticker="AAPL",
        contract_symbol="AAPL260425C00200000",
        option_type="call",
        strike=200.0,
        expiration_date=EXPIRY,
        side="buy",
        quantity=1,
        limit_price=3.50,
        status="pending",
    )
    db_session.add(order)
    db_session.flush()
    assert order.id is not None


def test_paper_order_unique_per_alert(db_session):
    sid = _add_symbol(db_session)
    alert = Alert(symbol_id=sid, ticker="AAPL", direction="bullish", score=83.5)
    db_session.add(alert)
    db_session.flush()

    db_session.add(
        PaperOrder(
            alert_id=alert.id,
            symbol_id=sid,
            ticker="AAPL",
            contract_symbol="AAPL260425C00200000",
            option_type="call",
            strike=200.0,
            expiration_date=EXPIRY,
            side="buy",
            quantity=1,
            limit_price=3.50,
            status="pending",
        ),
    )
    db_session.flush()

    _assert_duplicate_rejected(
        db_session,
        PaperOrder(
            alert_id=alert.id,
            symbol_id=sid,
            ticker="AAPL",
            contract_symbol="AAPL260425C00200000",
            option_type="call",
            strike=200.0,
            expiration_date=EXPIRY,
            side="buy",
            quantity=1,
            limit_price=3.50,
            status="pending",
        ),
    )


def test_paper_position_insert(db_session):
    sid = _add_symbol(db_session)
    pos = PaperPosition(
        symbol_id=sid,
        ticker="AAPL",
        contract_symbol="AAPL260425C00200000",
        option_type="call",
        strike=200.0,
        expiration_date=EXPIRY,
        quantity=1,
        entry_price=3.50,
        status="open",
    )
    db_session.add(pos)
    db_session.flush()
    assert pos.id is not None


def test_position_event_insert(db_session):
    sid = _add_symbol(db_session)
    pos = PaperPosition(
        symbol_id=sid,
        ticker="AAPL",
        contract_symbol="AAPL260425C00200000",
        option_type="call",
        strike=200.0,
        expiration_date=EXPIRY,
        quantity=1,
        entry_price=3.50,
        status="open",
    )
    db_session.add(pos)
    db_session.flush()

    ev = PositionEvent(
        position_id=pos.id,
        event_type="target1_hit",
        price_at_event=4.375,
    )
    db_session.add(ev)
    db_session.flush()
    assert ev.id is not None


def test_daily_metric_insert(db_session):
    metric = DailyMetric(
        metric_date=TODAY,
        total_signals=5,
        total_alerts=2,
        alerts_by_grade={"A-": 1, "B+": 1},
    )
    db_session.add(metric)
    db_session.flush()
    assert metric.id is not None


# --- Raw event tables ---


def test_raw_tradier_event_insert(db_session):
    ev = RawTradierEvent(received_at=NOW, payload={"type": "quote", "symbol": "AAPL"})
    db_session.add(ev)
    db_session.flush()
    assert ev.id is not None


def test_raw_alpaca_market_event_insert(db_session):
    ev = RawAlpacaMarketEvent(received_at=NOW, payload={"T": "q", "S": "AAPL"})
    db_session.add(ev)
    db_session.flush()
    assert ev.id is not None


def test_raw_official_news_event_insert(db_session):
    ev = RawOfficialNewsEvent(
        source_name="edgar",
        payload={"title": "8-K filing", "url": "https://example.com"},
        provider_event_id="edgar-raw-001",
    )
    db_session.add(ev)
    db_session.flush()
    assert ev.id is not None


def test_raw_marketaux_event_insert(db_session):
    ev = RawMarketauxEvent(
        source_name="marketaux",
        payload={"uuid": "abc123", "title": "AAPL news"},
        provider_event_id="mktaux-001",
    )
    db_session.add(ev)
    db_session.flush()
    assert ev.id is not None


def test_raw_news_backup_event_insert(db_session):
    ev = RawNewsBackupEvent(
        source_name="alpaca_news",
        payload={"id": 999, "headline": "test"},
    )
    db_session.add(ev)
    db_session.flush()
    assert ev.id is not None
