"""Unit tests for GET /api/v1/alerts and GET /api/v1/alerts/{id}."""

from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.v1.alerts import DetectorEvidenceOut, _build_evidence
from app.db.models.signals import DetectedEvent, SignalCandidate


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _candidate(**kwargs) -> MagicMock:
    defaults = dict(
        news_score=24.0,
        price_score=21.0,
        options_score=18.0,
        liquidity_score=13.0,
        data_confidence_score=10.0,
        provider_confidence=0.91,
        contract_bid=4.85,
        contract_ask=5.27,
        contract_spread_pct=0.08,
        contract_oi=2430,
        contract_volume=811,
        contract_selection_reason="ITM, tight spread",
        contract_rejection_json=[{"symbol": "205C", "reason": "too deep ITM"}],
    )
    defaults.update(kwargs)
    c = MagicMock(spec=SignalCandidate)
    for k, v in defaults.items():
        setattr(c, k, v)
    return c


def _news_event(**kwargs) -> MagicMock:
    defaults = dict(
        one_sentence_summary="Apple raises guidance.",
        event_type="earnings",
        polarity="positive",
        confidence=0.88,
        importance=0.80,
        source_tier=1,
    )
    defaults.update(kwargs)
    e = MagicMock(spec=DetectedEvent)
    for k, v in defaults.items():
        setattr(e, k, v)
    return e


def _price_event(**kwargs) -> MagicMock:
    defaults = dict(event_type="vwap_reclaim", confidence=0.82, polarity="positive")
    defaults.update(kwargs)
    e = MagicMock(spec=DetectedEvent)
    for k, v in defaults.items():
        setattr(e, k, v)
    return e


def _options_event(**kwargs) -> MagicMock:
    defaults = dict(
        event_type="elevated_call_volume",
        confidence=0.76,
        metadata_json={"relative_activity": 2.4},
    )
    defaults.update(kwargs)
    e = MagicMock(spec=DetectedEvent)
    for k, v in defaults.items():
        setattr(e, k, v)
    return e


# ---------------------------------------------------------------------------
# _build_evidence
# ---------------------------------------------------------------------------


def test_build_evidence_none_when_no_candidate():
    assert _build_evidence(None, None, None, None) is None


def test_build_evidence_returns_instance():
    ev = _build_evidence(_candidate(), _news_event(), None, None)
    assert isinstance(ev, DetectorEvidenceOut)


def test_build_evidence_news_fields():
    ev = _build_evidence(_candidate(), _news_event(), None, None)
    assert ev.news_summary == "Apple raises guidance."
    assert ev.news_event_type == "earnings"
    assert ev.news_polarity == "positive"
    assert ev.news_confidence == pytest.approx(0.88)
    assert ev.news_importance == pytest.approx(0.80)
    assert ev.news_source_tier == 1


def test_build_evidence_news_none_when_no_news_event():
    ev = _build_evidence(_candidate(), None, None, None)
    assert ev.news_summary is None
    assert ev.news_confidence is None
    assert ev.news_source_tier is None


def test_build_evidence_price_fields():
    ev = _build_evidence(_candidate(), None, _price_event(), None)
    assert ev.price_pattern == "vwap_reclaim"
    assert ev.price_confidence == pytest.approx(0.82)
    assert ev.price_polarity == "positive"


def test_build_evidence_price_none_when_no_price_event():
    ev = _build_evidence(_candidate(), None, None, None)
    assert ev.price_pattern is None
    assert ev.price_confidence is None


def test_build_evidence_options_fields():
    ev = _build_evidence(_candidate(), None, None, _options_event())
    assert ev.options_signal == "elevated_call_volume"
    assert ev.options_confidence == pytest.approx(0.76)
    assert ev.options_relative_activity == "2.4"


def test_build_evidence_options_relative_activity_missing_key():
    ev = _build_evidence(_candidate(), None, None, _options_event(metadata_json={"other": 1}))
    assert ev.options_relative_activity is None


def test_build_evidence_options_relative_activity_no_metadata():
    ev = _build_evidence(_candidate(), None, None, _options_event(metadata_json=None))
    assert ev.options_relative_activity is None


def test_build_evidence_scoring_from_candidate():
    ev = _build_evidence(_candidate(), None, None, None)
    assert ev.news_score == pytest.approx(24.0)
    assert ev.price_score == pytest.approx(21.0)
    assert ev.options_score == pytest.approx(18.0)
    assert ev.liquidity_score == pytest.approx(13.0)
    assert ev.data_confidence_score == pytest.approx(10.0)
    assert ev.provider_confidence == pytest.approx(0.91)


def test_build_evidence_scoring_none_when_null():
    ev = _build_evidence(_candidate(news_score=None, price_score=None), None, None, None)
    assert ev.news_score is None
    assert ev.price_score is None


def test_build_evidence_contract_from_candidate():
    ev = _build_evidence(_candidate(), None, None, None)
    assert ev.contract_bid == pytest.approx(4.85)
    assert ev.contract_ask == pytest.approx(5.27)
    assert ev.contract_spread_pct == pytest.approx(0.08)
    assert ev.contract_oi == 2430
    assert ev.contract_volume == 811
    assert ev.contract_selection_reason == "ITM, tight spread"
    assert ev.contract_rejection_json == [{"symbol": "205C", "reason": "too deep ITM"}]


def test_build_evidence_all_detectors_populated():
    ev = _build_evidence(_candidate(), _news_event(), _price_event(), _options_event())
    assert ev.news_summary is not None
    assert ev.price_pattern is not None
    assert ev.options_signal is not None
    assert ev.news_score is not None


# ---------------------------------------------------------------------------
# GET /api/v1/alerts/{alert_id} — endpoint-level tests via TestClient
# ---------------------------------------------------------------------------


def _make_app_with_empty_db():
    """Return a TestClient whose DB always returns an empty list."""
    from app.api.deps import get_db
    from app.main import app

    def override_get_db():
        db = MagicMock()
        # Build a chainable mock for the query → outerjoin × 4 → filter × n → order_by → limit → all
        chain = MagicMock()
        chain.outerjoin.return_value = chain
        chain.filter.return_value = chain
        chain.order_by.return_value = chain
        chain.limit.return_value = chain
        chain.all.return_value = []
        db.query.return_value = chain
        yield db

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=True)
    yield client
    app.dependency_overrides.pop(get_db, None)


def test_get_alert_not_found():
    from app.api.deps import get_db
    from app.main import app

    def override_get_db():
        db = MagicMock()
        chain = MagicMock()
        chain.outerjoin.return_value = chain
        chain.filter.return_value = chain
        chain.order_by.return_value = chain
        chain.limit.return_value = chain
        chain.all.return_value = []
        db.query.return_value = chain
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/alerts/99999")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Alert not found"
    finally:
        app.dependency_overrides.pop(get_db, None)


def test_list_alerts_returns_empty_list():
    from app.api.deps import get_db
    from app.main import app

    def override_get_db():
        db = MagicMock()
        chain = MagicMock()
        chain.outerjoin.return_value = chain
        chain.filter.return_value = chain
        chain.order_by.return_value = chain
        chain.limit.return_value = chain
        chain.all.return_value = []
        db.query.return_value = chain
        yield db

    app.dependency_overrides[get_db] = override_get_db
    try:
        client = TestClient(app)
        resp = client.get("/api/v1/alerts")
        assert resp.status_code == 200
        assert resp.json() == []
    finally:
        app.dependency_overrides.pop(get_db, None)
