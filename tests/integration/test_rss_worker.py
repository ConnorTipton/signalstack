"""Integration tests for RssWorker DB persistence.

Tests _write_entry directly with the transactional test DB session.
The RSS HTTP client is not exercised here.
"""

from datetime import UTC, datetime

from app.db.models.news import NewsArticle, NewsArticleTicker
from app.db.models.raw_events import RawOfficialNewsEvent
from app.ingest_news.rss_worker import RssWorker
from app.providers.official_feeds.rss import RssEntry

_NOW = datetime(2025, 1, 30, 21, 0, 0, tzinfo=UTC)

_ENTRY = RssEntry(
    provider_event_id="https://ir.apple.com/news/2025/q1-results",
    source_name="ir_apple",
    title="Apple Q1 2025 Results",
    url="https://ir.apple.com/news/2025/q1-results",
    published_at=_NOW,
    summary="Apple reported record Q1 revenue.",
    content_hash="b" * 64,
    raw={
        "id": "https://ir.apple.com/news/2025/q1-results",
        "title": "Apple Q1 2025 Results",
        "link": "https://ir.apple.com/news/2025/q1-results",
        "summary": "Apple reported record Q1 revenue.",
        "published": "2025-01-30T21:00:00+00:00",
        "source_name": "ir_apple",
    },
)


# ---------------------------------------------------------------------------
# Raw event
# ---------------------------------------------------------------------------


def test_write_entry_stores_raw_event(db_session):
    RssWorker._write_entry(db_session, _ENTRY, ["AAPL"], _NOW)
    db_session.flush()

    raw = db_session.query(RawOfficialNewsEvent).one()
    assert raw.source_name == "ir_apple"
    assert raw.source_tier == 1
    assert raw.provider_event_id == _ENTRY.provider_event_id
    assert raw.received_at == _NOW
    assert raw.content_hash == _ENTRY.content_hash
    assert raw.normalization_version == "1"


# ---------------------------------------------------------------------------
# Normalized article
# ---------------------------------------------------------------------------


def test_write_entry_stores_news_article(db_session):
    RssWorker._write_entry(db_session, _ENTRY, ["AAPL"], _NOW)
    db_session.flush()

    article = db_session.query(NewsArticle).one()
    assert article.title == "Apple Q1 2025 Results"
    assert article.source_name == "ir_apple"
    assert article.source_tier == 1
    assert article.provider_event_id == _ENTRY.provider_event_id
    assert article.url == _ENTRY.url
    assert article.body == "Apple reported record Q1 revenue."
    assert article.provider_published_at == _NOW


# ---------------------------------------------------------------------------
# Ticker associations
# ---------------------------------------------------------------------------


def test_write_entry_stores_single_ticker(db_session):
    RssWorker._write_entry(db_session, _ENTRY, ["AAPL"], _NOW)
    db_session.flush()

    article = db_session.query(NewsArticle).one()
    rows = db_session.query(NewsArticleTicker).all()
    assert len(rows) == 1
    assert rows[0].article_id == article.id
    assert rows[0].ticker == "AAPL"


def test_write_entry_stores_multiple_tickers(db_session):
    RssWorker._write_entry(db_session, _ENTRY, ["AAPL", "MSFT"], _NOW)
    db_session.flush()

    tickers = {r.ticker for r in db_session.query(NewsArticleTicker).all()}
    assert tickers == {"AAPL", "MSFT"}


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_write_entry_is_idempotent(db_session):
    RssWorker._write_entry(db_session, _ENTRY, ["AAPL"], _NOW)
    db_session.flush()
    RssWorker._write_entry(db_session, _ENTRY, ["AAPL"], _NOW)
    db_session.flush()

    assert db_session.query(NewsArticle).count() == 1
    assert db_session.query(RawOfficialNewsEvent).count() == 1
    assert db_session.query(NewsArticleTicker).count() == 1
