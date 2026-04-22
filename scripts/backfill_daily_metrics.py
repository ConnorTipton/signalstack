"""Backfill daily_metrics rows for a date range."""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

sys.path.insert(0, ".")

from app.db.session import SessionLocal
from app.execution.metrics_worker import DailyMetricsWorker


def iter_dates(start: date, end: date):
    """Yield inclusive dates from start through end."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backfill SignalStack daily metrics")
    parser.add_argument("--start", required=True, type=_parse_date, help="Start date YYYY-MM-DD")
    parser.add_argument("--end", required=True, type=_parse_date, help="End date YYYY-MM-DD")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.end < args.start:
        raise SystemExit("--end must be on or after --start")

    worker = DailyMetricsWorker()
    with SessionLocal() as db:
        for day in iter_dates(args.start, args.end):
            row = worker.run_once(db, metric_date=day)
            print(
                f"{row.metric_date}: signals={row.total_signals} alerts={row.total_alerts} "
                f"orders={row.total_paper_orders} closed={row.total_positions_closed}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
