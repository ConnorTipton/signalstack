"""Unit tests for the daily metrics backfill script helpers."""

from datetime import date

from scripts.backfill_daily_metrics import iter_dates


def test_iter_dates_is_inclusive():
    assert list(iter_dates(date(2026, 4, 20), date(2026, 4, 22))) == [
        date(2026, 4, 20),
        date(2026, 4, 21),
        date(2026, 4, 22),
    ]
