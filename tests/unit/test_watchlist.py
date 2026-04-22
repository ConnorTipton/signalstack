"""Unit tests for runtime watchlist parsing."""

import pytest

from app.core.watchlist import parse_rss_feeds, parse_tickers


def test_parse_tickers_normalizes_and_dedupes():
    assert parse_tickers(" aapl, MSFT, aapl ,, spy ") == ["AAPL", "MSFT", "SPY"]


def test_parse_tickers_rejects_empty_input():
    with pytest.raises(ValueError):
        parse_tickers(" , ")


def test_parse_rss_feeds_accepts_wire_and_ir_forms():
    feeds = parse_rss_feeds("wire|https://example.com/feed;ir_apple|https://ir/aapl|aapl")

    assert feeds[0].source_name == "wire"
    assert feeds[0].ticker is None
    assert feeds[1].source_name == "ir_apple"
    assert feeds[1].ticker == "AAPL"


def test_parse_rss_feeds_rejects_bad_entries():
    with pytest.raises(ValueError):
        parse_rss_feeds("missing-url-only")
