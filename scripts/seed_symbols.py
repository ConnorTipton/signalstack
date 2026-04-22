"""Seed the symbols table with the configured V1 universe."""

import sys

sys.path.insert(0, ".")

from app.core.config import settings
from app.core.watchlist import DEFAULT_SYMBOL_NAMES, parse_tickers
from app.db.models.symbols import Symbol
from app.db.session import SessionLocal


def main() -> None:
    symbols = [
        (ticker, DEFAULT_SYMBOL_NAMES.get(ticker, ticker))
        for ticker in parse_tickers(settings.monitored_tickers)
    ]
    with SessionLocal() as session:
        existing = {s.ticker for s in session.query(Symbol).all()}
        new_symbols = [
            Symbol(ticker=ticker, name=name) for ticker, name in symbols if ticker not in existing
        ]
        if new_symbols:
            session.add_all(new_symbols)
            session.commit()
            print(f"Seeded {len(new_symbols)} symbol(s): {[s.ticker for s in new_symbols]}")
        else:
            print("All symbols already present — nothing to seed.")


if __name__ == "__main__":
    main()
