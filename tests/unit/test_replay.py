"""Unit tests for Phase 10 Replay engine."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db
from app.main import app
from app.replay.event_player import EventPlayer
from app.replay.report import ReplayEvent, ReplayReport
from app.replay.scenario_runner import ScenarioRunner

client = TestClient(app)

_NOW = datetime(2026, 4, 21, 14, 0, tzinfo=UTC)
_START = _NOW - timedelta(hours=1)
_END = _NOW


# ---------------------------------------------------------------------------
# Fake DB infrastructure
# ---------------------------------------------------------------------------


class _FakeQuery:
    """Chainable query mock that ignores all filters and returns a fixed result."""

    def __init__(self, result: list) -> None:
        self._result = result

    def filter(self, *_, **__) -> "_FakeQuery":
        return self

    def all(self) -> list:
        return self._result

    def first(self):
        return self._result[0] if self._result else None

    def in_(self, *_) -> "_FakeQuery":
        return self

    def subquery(self) -> "_FakeQuery":
        return self


class _FakeDB:
    """Routes db.query(Model) to pre-loaded fixture lists by model class."""

    def __init__(self, **kw) -> None:
        from app.db.models.execution import Alert, PaperPosition
        from app.db.models.news import NewsArticle, NewsArticleTicker
        from app.db.models.raw_events import RawMarketauxEvent, RawOfficialNewsEvent
        from app.db.models.signals import DetectedEvent, SignalCandidate

        self._routes = {
            NewsArticle: kw.get("articles", []),
            NewsArticleTicker: [],
            DetectedEvent: kw.get("detected", []),
            SignalCandidate: kw.get("signals", []),
            Alert: kw.get("alerts", []),
            PaperPosition: kw.get("positions", []),
            RawOfficialNewsEvent: kw.get("raw_official", []),
            RawMarketauxEvent: kw.get("raw_marketaux", []),
        }

    def query(self, model, *_) -> _FakeQuery:
        cls = getattr(model, "class_", model)
        return _FakeQuery(self._routes.get(cls, []))


# ---------------------------------------------------------------------------
# Sample data factories
# ---------------------------------------------------------------------------


def _article(
    id: int = 1,
    created_at: datetime = _NOW,
    source_name: str = "edgar_rss",
    source_tier: int = 1,
    provider_event_id: str | None = "ev1",
    received_at: datetime = _NOW,
    title: str = "AAPL beats earnings",
    is_duplicate: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        created_at=created_at,
        source_name=source_name,
        source_tier=source_tier,
        provider_event_id=provider_event_id,
        received_at=received_at,
        title=title,
        is_duplicate=is_duplicate,
    )


def _detected(
    id: int = 1,
    detected_at: datetime = _NOW,
    ticker: str = "AAPL",
    detector: str = "A",
    event_type: str = "earnings",
    polarity: str = "positive",
    source_tier: int = 1,
    importance: float = 0.8,
    confidence: float = 0.9,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        detected_at=detected_at,
        ticker=ticker,
        detector=detector,
        event_type=event_type,
        polarity=polarity,
        source_tier=source_tier,
        importance=importance,
        confidence=confidence,
    )


def _signal(
    id: int = 1,
    created_at: datetime = _NOW,
    ticker: str = "AAPL",
    score: float = 75.0,
    grade: str = "B",
    status: str = "promoted",
    rejection_reason: str | None = None,
    news_event_id: int | None = None,
    price_event_id: int | None = None,
    options_event_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        created_at=created_at,
        ticker=ticker,
        score=score,
        grade=grade,
        status=status,
        rejection_reason=rejection_reason,
        news_event_id=news_event_id,
        price_event_id=price_event_id,
        options_event_id=options_event_id,
    )


def _alert_row(
    id: int = 1,
    created_at: datetime = _NOW,
    ticker: str = "AAPL",
    score: float = 75.0,
    grade: str = "B",
    sent_at: datetime | None = _NOW,
    signal_candidate_id: int | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        created_at=created_at,
        ticker=ticker,
        score=score,
        grade=grade,
        sent_at=sent_at,
        signal_candidate_id=signal_candidate_id,
    )


def _position(
    id: int = 1,
    opened_at: datetime = _NOW,
    closed_at: datetime | None = None,
    status: str = "open",
    ticker: str = "AAPL",
    contract_symbol: str = "AAPL250501C00190000",
    entry_price: float = 2.50,
    exit_price: float | None = None,
    exit_reason: str | None = None,
    pnl: float | None = None,
    pnl_pct: float | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=id,
        opened_at=opened_at,
        closed_at=closed_at,
        status=status,
        ticker=ticker,
        contract_symbol=contract_symbol,
        entry_price=entry_price,
        exit_price=exit_price,
        exit_reason=exit_reason,
        pnl=pnl,
        pnl_pct=pnl_pct,
    )


def _raw_official(id: int = 10, provider_event_id: str = "ev1") -> SimpleNamespace:
    return SimpleNamespace(id=id, provider_event_id=provider_event_id)


def _raw_marketaux(id: int = 20, provider_event_id: str = "mx1") -> SimpleNamespace:
    return SimpleNamespace(id=id, provider_event_id=provider_event_id)


# ---------------------------------------------------------------------------
# EventPlayer — load_events
# ---------------------------------------------------------------------------


def test_load_events_returns_news_article_kind():
    db = _FakeDB(articles=[_article()])
    events = EventPlayer().load_events(db, _START, _END)
    assert any(e.event_kind == "news_article" for e in events)


def test_load_events_returns_detected_event_kind():
    db = _FakeDB(detected=[_detected()])
    events = EventPlayer().load_events(db, _START, _END)
    assert any(e.event_kind == "detected_event" for e in events)


def test_load_events_returns_signal_candidate_kind():
    db = _FakeDB(signals=[_signal()])
    events = EventPlayer().load_events(db, _START, _END)
    assert any(e.event_kind == "signal_candidate" for e in events)


def test_load_events_returns_alert_kind():
    db = _FakeDB(alerts=[_alert_row()])
    events = EventPlayer().load_events(db, _START, _END)
    assert any(e.event_kind == "alert" for e in events)


def test_load_events_returns_position_open_kind():
    db = _FakeDB(positions=[_position()])
    events = EventPlayer().load_events(db, _START, _END)
    assert any(e.event_kind == "position_open" for e in events)


def test_load_events_sorted_by_time():
    early = _NOW - timedelta(minutes=30)
    late = _NOW
    db = _FakeDB(
        detected=[_detected(detected_at=late)],
        articles=[_article(created_at=early)],
    )
    events = EventPlayer().load_events(db, _START, _END)
    times = [e.event_time for e in events]
    assert times == sorted(times)


def test_load_events_empty_window_returns_empty():
    db = _FakeDB()
    assert EventPlayer().load_events(db, _START, _END) == []


def test_load_events_detected_event_has_detector_in_details():
    db = _FakeDB(detected=[_detected(detector="A", event_type="earnings")])
    events = EventPlayer().load_events(db, _START, _END)
    detected = [e for e in events if e.event_kind == "detected_event"]
    assert detected[0].details["detector"] == "A"
    assert detected[0].details["event_type"] == "earnings"


def test_load_events_alert_sent_flag_in_details():
    db = _FakeDB(alerts=[_alert_row(sent_at=_NOW)])
    events = EventPlayer().load_events(db, _START, _END)
    alert_ev = next(e for e in events if e.event_kind == "alert")
    assert alert_ev.details["sent"] is True


def test_load_events_unsent_alert_sent_flag_false():
    db = _FakeDB(alerts=[_alert_row(sent_at=None)])
    events = EventPlayer().load_events(db, _START, _END)
    alert_ev = next(e for e in events if e.event_kind == "alert")
    assert alert_ev.details["sent"] is False


# ---------------------------------------------------------------------------
# EventPlayer — build_postmortems
# ---------------------------------------------------------------------------


def test_build_postmortems_empty_when_no_detected_events():
    db = _FakeDB()
    assert EventPlayer().build_postmortems(db, _START, _END) == []


def test_build_postmortems_groups_by_detector():
    db = _FakeDB(
        detected=[_detected(id=1, detector="A"), _detected(id=2, detector="B")],
    )
    postmortems = EventPlayer().build_postmortems(db, _START, _END)
    detectors = {p.detector for p in postmortems}
    assert detectors == {"A", "B"}


def test_build_postmortems_counts_total_events_per_detector():
    db = _FakeDB(
        detected=[
            _detected(id=1, detector="A"),
            _detected(id=2, detector="A"),
            _detected(id=3, detector="C"),
        ],
    )
    postmortems = EventPlayer().build_postmortems(db, _START, _END)
    by_det = {p.detector: p for p in postmortems}
    assert by_det["A"].total_events == 2
    assert by_det["C"].total_events == 1


def test_build_postmortems_counts_signal_linkage():
    db = _FakeDB(
        detected=[_detected(id=1, detector="A")],
        signals=[_signal(id=10, news_event_id=1, status="watch")],
    )
    pm = EventPlayer().build_postmortems(db, _START, _END)[0]
    assert pm.events_that_led_to_signal == 1
    assert pm.events_that_led_to_alert == 0


def test_build_postmortems_counts_alert_linkage():
    db = _FakeDB(
        detected=[_detected(id=1, detector="A")],
        signals=[_signal(id=10, news_event_id=1, status="promoted")],
        alerts=[_alert_row(id=5, signal_candidate_id=10)],
    )
    pm = EventPlayer().build_postmortems(db, _START, _END)[0]
    assert pm.events_that_led_to_signal == 1
    assert pm.events_that_led_to_alert == 1


# ---------------------------------------------------------------------------
# EventPlayer — build_source_traces
# ---------------------------------------------------------------------------


def test_build_source_traces_tier1_matches_raw_official():
    db = _FakeDB(
        articles=[_article(source_tier=1, provider_event_id="ev1")],
        raw_official=[_raw_official(id=10, provider_event_id="ev1")],
    )
    traces = EventPlayer().build_source_traces(db, _START, _END)
    assert len(traces) == 1
    assert traces[0].raw_table == "raw_official_news_events"
    assert traces[0].raw_event_id == 10


def test_build_source_traces_tier2_matches_raw_marketaux():
    db = _FakeDB(
        articles=[_article(source_tier=2, provider_event_id="mx1")],
        raw_marketaux=[_raw_marketaux(id=20, provider_event_id="mx1")],
    )
    traces = EventPlayer().build_source_traces(db, _START, _END)
    assert traces[0].raw_table == "raw_marketaux_events"
    assert traces[0].raw_event_id == 20


def test_build_source_traces_no_raw_match_returns_none_fields():
    db = _FakeDB(
        articles=[_article(source_tier=1, provider_event_id="ev_missing")],
        raw_official=[],
    )
    traces = EventPlayer().build_source_traces(db, _START, _END)
    assert traces[0].raw_table is None
    assert traces[0].raw_event_id is None


def test_build_source_traces_no_provider_event_id_skips_lookup():
    db = _FakeDB(articles=[_article(provider_event_id=None)])
    traces = EventPlayer().build_source_traces(db, _START, _END)
    assert traces[0].raw_table is None


# ---------------------------------------------------------------------------
# ScenarioRunner
# ---------------------------------------------------------------------------


def _mock_player(timeline: list | None = None) -> MagicMock:
    p = MagicMock(spec=EventPlayer)
    p.load_events.return_value = timeline or []
    p.build_postmortems.return_value = []
    p.build_source_traces.return_value = []
    return p


def _make_event(kind: str, ticker: str = "AAPL", details: dict | None = None) -> ReplayEvent:
    return ReplayEvent(
        event_time=_NOW,
        event_kind=kind,
        ticker=ticker,
        row_id=1,
        details=details or {},
    )


def test_runner_returns_replay_report():
    runner = ScenarioRunner(player=_mock_player())
    report = runner.run(MagicMock(), _START, _END)
    assert isinstance(report, ReplayReport)


def test_runner_counts_news_articles():
    timeline = [_make_event("news_article"), _make_event("news_article")]
    runner = ScenarioRunner(player=_mock_player(timeline))
    report = runner.run(MagicMock(), _START, _END)
    assert report.total_news_articles == 2


def test_runner_counts_only_sent_alerts():
    timeline = [
        _make_event("alert", details={"sent": True, "score": 75.0, "grade": "B"}),
        _make_event("alert", details={"sent": False, "score": 60.0, "grade": "C"}),
    ]
    runner = ScenarioRunner(player=_mock_player(timeline))
    report = runner.run(MagicMock(), _START, _END)
    assert report.total_alerts_sent == 1


def test_runner_win_rate_none_when_no_closed_positions():
    runner = ScenarioRunner(player=_mock_player())
    report = runner.run(MagicMock(), _START, _END)
    assert report.win_rate is None


def test_runner_win_rate_calculation():
    timeline = [
        _make_event(
            "position_close",
            details={"pnl": 50.0, "pnl_pct": 0.20, "exit_price": 3.0, "exit_reason": "time_stop"},
        ),
        _make_event(
            "position_close",
            details={
                "pnl": -25.0,
                "pnl_pct": -0.10,
                "exit_price": 2.25,
                "exit_reason": "time_stop",
            },
        ),
    ]
    runner = ScenarioRunner(player=_mock_player(timeline))
    report = runner.run(MagicMock(), _START, _END)
    assert report.win_rate == pytest.approx(0.5)


def test_runner_realized_pnl():
    timeline = [
        _make_event(
            "position_close",
            details={"pnl": 50.0, "exit_price": 3.0, "pnl_pct": 0.20, "exit_reason": "time_stop"},
        ),
        _make_event(
            "position_close",
            details={"pnl": 30.0, "exit_price": 3.0, "pnl_pct": 0.12, "exit_reason": "time_stop"},
        ),
    ]
    runner = ScenarioRunner(player=_mock_player(timeline))
    report = runner.run(MagicMock(), _START, _END)
    assert report.realized_pnl == pytest.approx(80.0)


def test_runner_truncates_timeline_to_max_events():
    timeline = [_make_event("news_article") for _ in range(10)]
    runner = ScenarioRunner(player=_mock_player(timeline))
    report = runner.run(MagicMock(), _START, _END, max_timeline_events=3)
    assert len(report.timeline) == 3


def test_runner_includes_tickers_in_report():
    runner = ScenarioRunner(player=_mock_player())
    report = runner.run(MagicMock(), _START, _END, tickers=["AAPL", "MSFT"])
    assert set(report.tickers) == {"AAPL", "MSFT"}


def test_runner_empty_tickers_returns_all():
    runner = ScenarioRunner(player=_mock_player())
    report = runner.run(MagicMock(), _START, _END, tickers=[])
    assert report.tickers == []


# ---------------------------------------------------------------------------
# GET /api/v1/replay
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_overrides():
    yield
    app.dependency_overrides.clear()


def _db_override():
    db = MagicMock()
    db.query.return_value.filter.return_value = db.query.return_value
    db.query.return_value.all.return_value = []
    db.query.return_value.first.return_value = None
    return db


def _url(extra: str = "") -> str:
    """Build a replay URL with properly formatted datetime params."""
    ws = _START.strftime("%Y-%m-%dT%H:%M:%SZ")
    we = _END.strftime("%Y-%m-%dT%H:%M:%SZ")
    base = f"/api/v1/replay?window_start={ws}&window_end={we}"
    return base + extra


def test_replay_endpoint_returns_200():
    app.dependency_overrides[get_db] = lambda: _db_override()
    assert client.get(_url()).status_code == 200


def test_replay_endpoint_returns_report_structure():
    app.dependency_overrides[get_db] = lambda: _db_override()
    data = client.get(_url()).json()
    assert "timeline" in data
    assert "detector_postmortems" in data
    assert "provider_traces" in data
    assert "total_news_articles" in data
    assert "win_rate" in data


def test_replay_endpoint_missing_params_returns_422():
    app.dependency_overrides[get_db] = lambda: _db_override()
    assert client.get("/api/v1/replay").status_code == 422


def test_replay_endpoint_accepts_ticker_filter():
    app.dependency_overrides[get_db] = lambda: _db_override()
    assert client.get(_url("&ticker=AAPL")).status_code == 200
