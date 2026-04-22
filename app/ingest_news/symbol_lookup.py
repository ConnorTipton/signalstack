"""Helpers for attaching normalized news rows to seeded symbols."""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models.symbols import Symbol


def resolve_symbol_ids(db: Session, tickers: list[str]) -> dict[str, int]:
    """Return ``ticker -> symbol_id`` for tickers present in the symbols table."""
    normalized = sorted({ticker.strip().upper() for ticker in tickers if ticker.strip()})
    if not normalized:
        return {}
    rows = db.query(Symbol).filter(Symbol.ticker.in_(normalized)).all()
    return {row.ticker: row.id for row in rows}
