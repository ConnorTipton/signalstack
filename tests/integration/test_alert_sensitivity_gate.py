"""Integration test: sensitivity gate end-to-end with grade fidelity check.

Seeds promoted SignalCandidate rows of grades A/B/C, runs AlertWorker.run_once,
and asserts:
  1. Only the grades allowed by the configured sensitivity mode produce Alerts.
  2. Each emitted Alert carries the candidate's actual grade (grade fidelity).
  3. Rejected candidates are marked rejected with a sensitivity_gate reason.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.alerts.worker import AlertWorker
from app.core import desktop_state
from app.db.models.execution import Alert
from app.db.models.signals import SignalCandidate
from app.db.models.symbols import Symbol

pytestmark = pytest.mark.integration


@pytest.fixture
def state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect desktop_state.STATE_FILE to a per-test temp path."""
    p = tmp_path / "desktop_state.json"
    monkeypatch.setattr(desktop_state, "STATE_FILE", p)
    return p


@pytest.fixture
def no_commit_session(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Session:
    """Patch db_session.commit -> flush so the worker's commits don't end
    the outer test transaction (which the conftest rolls back on teardown).
    """
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    return db_session


def _make_candidate(
    db: Session, *, ticker: str, grade: str, score: float
) -> SignalCandidate:
    """Insert a 'promoted' candidate with a contract attached so it would alert."""
    sym = db.query(Symbol).filter_by(ticker=ticker).first()
    if sym is None:
        sym = Symbol(ticker=ticker, name=ticker)
        db.add(sym)
        db.flush()

    candidate = SignalCandidate(
        symbol_id=sym.id,
        ticker=ticker,
        score=score,
        grade=grade,
        status="promoted",
        promoted_at=datetime.now(UTC),
        contract_symbol=f"{ticker}241220C00100000",
        contract_strike=100.0,
        contract_type="call",
        contract_bid=1.0,
        contract_ask=1.05,
        contract_spread_pct=0.05,
        contract_oi=1000,
        contract_volume=500,
    )
    db.add(candidate)
    db.flush()
    return candidate


@pytest.mark.parametrize(
    "mode,expected_grades",
    [
        ("high", {"A"}),
        ("medium", {"A", "B"}),
        ("low", {"A", "B", "C"}),
    ],
)
def test_sensitivity_gate_admits_correct_grades(
    no_commit_session: Session,
    state_file: Path,
    mode: str,
    expected_grades: set[str],
) -> None:
    db = no_commit_session
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"sensitivity_mode": mode}))

    seeds = [
        ("AAA", "A", 90.0),
        ("BBB", "B", 75.0),
        ("CCC", "C", 67.0),
    ]
    for ticker, grade, score in seeds:
        _make_candidate(db, ticker=ticker, grade=grade, score=score)
    db.flush()

    worker = AlertWorker(telegram_client=None, dry_run=True)
    worker.run_once(db)
    db.flush()

    alerts = db.query(Alert).all()
    emitted_grades = {a.grade for a in alerts}
    assert emitted_grades == expected_grades, (
        f"mode={mode}: expected alerts for grades {expected_grades}, "
        f"got {emitted_grades}"
    )

    # Grade fidelity: each emitted Alert carries the candidate's true grade,
    # not a sensitivity-derived label.
    for alert in alerts:
        candidate = (
            db.query(SignalCandidate)
            .filter_by(id=alert.signal_candidate_id)
            .one()
        )
        assert alert.grade == candidate.grade, (
            "alert grade must equal candidate grade (grade fidelity)"
        )

    # Rejected candidates have a sensitivity_gate rejection_reason.
    rejected = (
        db.query(SignalCandidate).filter_by(status="rejected").all()
    )
    expected_rejected_grades = {"A", "B", "C"} - expected_grades
    rejected_grades = {c.grade for c in rejected}
    assert rejected_grades == expected_rejected_grades

    for c in rejected:
        assert c.rejection_reason is not None
        assert c.rejection_reason.startswith(f"sensitivity_gate:{mode}:grade_")
        assert c.rejected_at is not None
