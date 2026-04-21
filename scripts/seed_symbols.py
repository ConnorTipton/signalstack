"""Seed the symbols table with the V1 universe from blueprint §6."""

import sys

sys.path.insert(0, ".")

from app.db.models.symbols import Symbol
from app.db.session import SessionLocal

SYMBOLS: list[tuple[str, str]] = [
    ("SPY", "SPDR S&P 500 ETF Trust"),
    ("QQQ", "Invesco QQQ Trust"),
    ("IWM", "iShares Russell 2000 ETF"),
    ("AAPL", "Apple Inc."),
    ("MSFT", "Microsoft Corporation"),
    ("NVDA", "NVIDIA Corporation"),
    ("AMZN", "Amazon.com Inc."),
    ("META", "Meta Platforms Inc."),
    ("TSLA", "Tesla Inc."),
    ("AMD", "Advanced Micro Devices Inc."),
    ("NFLX", "Netflix Inc."),
    ("GOOGL", "Alphabet Inc."),
]


def main() -> None:
    with SessionLocal() as session:
        existing = {s.ticker for s in session.query(Symbol).all()}
        new_symbols = [
            Symbol(ticker=ticker, name=name) for ticker, name in SYMBOLS if ticker not in existing
        ]
        if new_symbols:
            session.add_all(new_symbols)
            session.commit()
            print(f"Seeded {len(new_symbols)} symbol(s): {[s.ticker for s in new_symbols]}")
        else:
            print("All symbols already present — nothing to seed.")


if __name__ == "__main__":
    main()
