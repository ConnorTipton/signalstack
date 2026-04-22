"""Integration tests for EdgarWorker DB persistence.

Tests _write_entry directly with the transactional test DB session.
The EDGAR HTTP client is not exercised here.
"""

from datetime import UTC, datetime

from app.db.models.news import NewsArticle, NewsArticleTicker
from app.db.models.raw_events import RawOfficialNewsEvent
from app.db.models.symbols import Symbol
from app.ingest_news.edgar_worker import EdgarWorker
from app.providers.official_feeds.edgar import EdgarEntry

_NOW = datetime(2025, 1, 24, 21, 44, 14, tzinfo=UTC)

_ENTRY = EdgarEntry(
    provider_event_id="urn:tag:security.gov,2008:accession-number=0000320193-25-000006",
    ticker="AAPL",
    title="8-K - APPLE INC",
    url="https://www.sec.gov/Archives/edgar/data/320193/000032019325000006/0000320193-25-000006-index.htm",
    published_at=_NOW,
    summary="Current report on Form 8-K",
    content_hash="a" * 64,
    raw={
        "id": "urn:tag:security.gov,2008:accession-number=0000320193-25-000006",
        "title": "8-K - APPLE INC",
        "link": "https://www.sec.gov/Archives/edgar/data/320193/...",
        "summary": "Current report on Form 8-K",
        "published": "2025-01-24T21:44:14+00:00",
        "ticker": "AAPL",
    },
)


# ---------------------------------------------------------------------------
# Raw event
# ---------------------------------------------------------------------------


def test_write_entry_stores_raw_event(db_session):
    EdgarWorker._write_entry(db_session, _ENTRY, _NOW)
    db_session.flush()

    raw = db_session.query(RawOfficialNewsEvent).one()
    assert raw.source_name == "edgar"
    assert raw.source_tier == 1
    assert raw.provider_event_id == _ENTRY.provider_event_id
    assert raw.received_at == _NOW
    assert raw.content_hash == _ENTRY.content_hash
    assert raw.normalization_version == "1"
    assert raw.payload["ticker"] == "AAPL"


# ---------------------------------------------------------------------------
# Normalized article
# ---------------------------------------------------------------------------


def test_write_entry_stores_news_article(db_session):
    EdgarWorker._write_entry(db_session, _ENTRY, _NOW)
    db_session.flush()

    article = db_session.query(NewsArticle).one()
    assert article.title == "8-K - APPLE INC"
    assert article.source_name == "edgar"
    assert article.source_tier == 1
    assert article.provider_event_id == _ENTRY.provider_event_id
    assert article.url == _ENTRY.url
    assert article.body == "Current report on Form 8-K"
    assert article.provider_published_at == _NOW


# ---------------------------------------------------------------------------
# Ticker association
# ---------------------------------------------------------------------------


def test_write_entry_stores_ticker_association(db_session):
    db_session.add(Symbol(ticker="AAPL", name="Apple Inc."))
    db_session.flush()

    EdgarWorker._write_entry(db_session, _ENTRY, _NOW)
    db_session.flush()

    article = db_session.query(NewsArticle).one()
    ticker_row = db_session.query(NewsArticleTicker).one()
    assert ticker_row.article_id == article.id
    assert ticker_row.ticker == "AAPL"
    assert ticker_row.symbol_id is not None


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_write_entry_is_idempotent(db_session):
    EdgarWorker._write_entry(db_session, _ENTRY, _NOW)
    db_session.flush()
    EdgarWorker._write_entry(db_session, _ENTRY, _NOW)
    db_session.flush()

    assert db_session.query(NewsArticle).count() == 1
    assert db_session.query(RawOfficialNewsEvent).count() == 1
    assert db_session.query(NewsArticleTicker).count() == 1
