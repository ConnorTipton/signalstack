"""Unit tests for worker startup helpers."""

from app.db.models.symbols import Symbol
from app.main_workers import _ensure_db_ready


class _Inspector:
    def get_table_names(self):
        return ["news_articles"]


class _Query:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_):
        return self

    def all(self):
        return [(row,) for row in self._rows]


class _Session:
    def __init__(self, existing):
        self._existing = existing
        self.added = []
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def get_bind(self):
        return object()

    def query(self, *_):
        return _Query(self._existing)

    def add_all(self, rows):
        self.added.extend(rows)

    def commit(self):
        self.committed = True


def test_ensure_db_ready_seeds_only_missing_symbols(monkeypatch):
    session = _Session(existing=["AAPL"])
    monkeypatch.setattr("sqlalchemy.inspect", lambda _: _Inspector())
    monkeypatch.setattr("app.db.session.SessionLocal", lambda: session)

    _ensure_db_ready(["AAPL", "MSFT"])

    assert [row.ticker for row in session.added] == ["MSFT"]
    assert all(isinstance(row, Symbol) for row in session.added)
    assert session.committed is True
