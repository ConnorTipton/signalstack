"""Integration tests for MarketauxWorker DB persistence.

Tests _write_article directly with the transactional test DB session.
The Marketaux HTTP client is not exercised here.
"""

from dataclasses import replace
from datetime import UTC, datetime

from app.db.models.news import NewsArticle, NewsArticleTicker
from app.db.models.raw_events import RawMarketauxEvent
from app.db.models.symbols import Symbol
from app.ingest_news.marketaux_worker import MarketauxWorker
from app.providers.marketaux.client import MarketauxArticle

_NOW = datetime(2025, 1, 30, 21, 0, 0, tzinfo=UTC)

_ARTICLE = MarketauxArticle(
    uuid="abc-123-def-456",
    title="Apple Reports Record Q1 Revenue",
    url="https://reuters.com/tech/apple-q1-2025",
    published_at=_NOW,
    source="Reuters",
    summary="Apple Inc. announced record Q1 revenue.",
    tickers=["AAPL"],
    content_hash="c" * 64,
    raw={"uuid": "abc-123-def-456", "title": "Apple Reports Record Q1 Revenue"},
)


# ---------------------------------------------------------------------------
# Raw event
# ---------------------------------------------------------------------------


def test_write_article_stores_raw_event(db_session):
    MarketauxWorker._write_article(db_session, _ARTICLE, _NOW)
    db_session.flush()

    raw = db_session.query(RawMarketauxEvent).one()
    assert raw.source_name == "marketaux"
    assert raw.source_tier == 2
    assert raw.provider_event_id == _ARTICLE.uuid
    assert raw.received_at == _NOW
    assert raw.content_hash == _ARTICLE.content_hash
    assert raw.normalization_version == "1"


# ---------------------------------------------------------------------------
# Normalized article
# ---------------------------------------------------------------------------


def test_write_article_stores_news_article(db_session):
    MarketauxWorker._write_article(db_session, _ARTICLE, _NOW)
    db_session.flush()

    article = db_session.query(NewsArticle).one()
    assert article.title == "Apple Reports Record Q1 Revenue"
    assert article.source_name == "marketaux"
    assert article.source_tier == 2
    assert article.provider_event_id == _ARTICLE.uuid
    assert article.url == _ARTICLE.url
    assert article.author == "Reuters"
    assert article.is_duplicate is False
    assert article.duplicate_of_id is None


# ---------------------------------------------------------------------------
# Ticker associations
# ---------------------------------------------------------------------------


def test_write_article_stores_ticker_rows(db_session):
    db_session.add(Symbol(ticker="AAPL", name="Apple Inc."))
    db_session.flush()

    MarketauxWorker._write_article(db_session, _ARTICLE, _NOW)
    db_session.flush()

    article = db_session.query(NewsArticle).one()
    rows = db_session.query(NewsArticleTicker).all()
    assert len(rows) == 1
    assert rows[0].article_id == article.id
    assert rows[0].ticker == "AAPL"
    assert rows[0].symbol_id is not None


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_write_article_is_idempotent(db_session):
    MarketauxWorker._write_article(db_session, _ARTICLE, _NOW)
    db_session.flush()
    MarketauxWorker._write_article(db_session, _ARTICLE, _NOW)
    db_session.flush()

    assert db_session.query(NewsArticle).count() == 1
    assert db_session.query(RawMarketauxEvent).count() == 1
    assert db_session.query(NewsArticleTicker).count() == 1


# ---------------------------------------------------------------------------
# Dedup — cross-source (Tier 1 URL match)
# ---------------------------------------------------------------------------


def test_write_article_marked_duplicate_when_tier1_url_exists(db_session):
    # Pre-insert a Tier 1 article with the same URL
    tier1 = NewsArticle(
        source_name="edgar",
        source_tier=1,
        title="Apple Q1 Results Press Release",
        url=_ARTICLE.url,
        received_at=_NOW,
        normalization_version="1",
    )
    db_session.add(tier1)
    db_session.flush()

    MarketauxWorker._write_article(db_session, _ARTICLE, _NOW)
    db_session.flush()

    mkt = db_session.query(NewsArticle).filter_by(source_name="marketaux").one()
    assert mkt.is_duplicate is True
    assert mkt.duplicate_of_id == tier1.id


def test_write_article_duplicate_skips_ticker_rows_for_tier1_match(db_session):
    tier1 = NewsArticle(
        source_name="edgar",
        source_tier=1,
        title="Apple Q1 Results Press Release",
        url=_ARTICLE.url,
        received_at=_NOW,
        normalization_version="1",
    )
    db_session.add(tier1)
    db_session.flush()

    MarketauxWorker._write_article(db_session, _ARTICLE, _NOW)
    db_session.flush()

    assert db_session.query(NewsArticleTicker).count() == 0


# ---------------------------------------------------------------------------
# Dedup — same-title hash (content_hash match)
# ---------------------------------------------------------------------------


def test_write_article_marked_duplicate_when_same_content_hash_exists(db_session):
    # Pre-insert another Marketaux article with the same content_hash
    earlier = NewsArticle(
        source_name="marketaux",
        source_tier=2,
        provider_event_id="earlier-uuid",
        title="Apple Reports Record Q1 Revenue",
        url="https://other-source.com/apple-q1",
        received_at=_NOW,
        content_hash=_ARTICLE.content_hash,
        normalization_version="1",
    )
    db_session.add(earlier)
    db_session.flush()

    MarketauxWorker._write_article(db_session, _ARTICLE, _NOW)
    db_session.flush()

    mkt = db_session.query(NewsArticle).filter_by(provider_event_id=_ARTICLE.uuid).one()
    assert mkt.is_duplicate is True
    assert mkt.duplicate_of_id == earlier.id


def test_write_article_preserves_raw_rows_for_same_content_hash(db_session):
    first = replace(
        _ARTICLE,
        uuid="raw-uuid-1",
        url="https://example.com/one",
        raw={"uuid": "raw-uuid-1", "title": _ARTICLE.title},
    )
    second = replace(
        _ARTICLE,
        uuid="raw-uuid-2",
        url="https://example.com/two",
        raw={"uuid": "raw-uuid-2", "title": _ARTICLE.title},
    )

    MarketauxWorker._write_article(db_session, first, _NOW)
    db_session.flush()
    MarketauxWorker._write_article(db_session, second, _NOW)
    db_session.flush()

    raw_rows = db_session.query(RawMarketauxEvent).all()
    assert len(raw_rows) == 2
    assert {row.provider_event_id for row in raw_rows} == {"raw-uuid-1", "raw-uuid-2"}
