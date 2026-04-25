# SignalStack Desktop App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PyWebView desktop app that wraps the existing SignalStack dashboard, controls workers/API as subprocesses (with Docker auto-launch), and adds High/Medium/Low sensitivity as an alert-time grade gate.

**Architecture:** Python-only addition. New module `app/desktop/` manages subprocesses and exposes a JS API to a webview embedding `web/SignalStack.html`. Sensitivity setting persists at `~/.signalstack/desktop_state.json`; alert worker re-reads it each loop iteration for live updates. New Control/Settings tabs added to existing dashboard sidebar.

**Tech Stack:** Python 3.12, PyWebView (new dep), `subprocess.Popen`, FastAPI (existing), React via CDN (existing).

**Spec:** [`docs/superpowers/specs/2026-04-24-signalstack-desktop-app-design.md`](../specs/2026-04-24-signalstack-desktop-app-design.md)

---

## Conventions

- All commands run from repo root unless stated otherwise.
- `uv run pytest -xvs` is the test command (-x stops on first failure, -v verbose, -s shows print output).
- After every task: `uv run ruff check .` must pass and `uv run ruff format .` should leave files unchanged. The plan calls this out only when files actually change.
- `_test` DB integration tests use the existing conftest.py fixtures.
- Commits use Conventional Commits style (feat/fix/test/chore).
- Each task ends with a commit. Do not batch.

---

## Task 1: Add `pywebview` dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1.1: Add pywebview to dependencies**

Edit `pyproject.toml` to add `pywebview` to the main `dependencies` list (it's a runtime dep when the user runs the desktop app, not a dev-only tool):

```toml
dependencies = [
    "fastapi>=0.115.0,<0.116",
    "uvicorn[standard]>=0.32.0,<0.33",
    "sqlalchemy>=2.0.36,<2.1",
    "alembic>=1.14.0,<1.15",
    "psycopg[binary]>=3.2.3,<3.3",
    "pydantic>=2.10.0,<3.0",
    "pydantic-settings>=2.7.0,<3.0",
    "httpx>=0.28.0,<0.29",
    "feedparser>=6.0.11,<7.0",
    "python-telegram-bot>=21.9,<22.0",
    "anthropic>=0.40.0,<1.0",
    "pywebview>=5.4,<6.0",
]
```

- [ ] **Step 1.2: Install the new dependency**

Run: `uv sync --extra dev`

Expected: lockfile updates, pywebview and its transitive deps install successfully.

- [ ] **Step 1.3: Verify import works**

Run: `uv run python -c "import webview; from importlib.metadata import version; print(version('pywebview'))"`

Expected: prints a version like `5.4`. (Note: pywebview 5.x does not expose `__version__` on the module itself; use `importlib.metadata.version()`.) If it errors with a Cocoa/Qt warning on macOS, that's expected at this point (no window is being created yet) — only the import needs to succeed.

- [ ] **Step 1.4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: add pywebview dependency for desktop app"
```

---

## Task 2: Create `desktop_state.py` — sensitivity read

**Files:**
- Create: `app/core/desktop_state.py`
- Create: `tests/unit/test_desktop_state.py`

**Why this file lives in `app/core/`:** Both the desktop app's `js_api` and the alert worker need to read the sensitivity setting. `app/core/` is the right shared home (the spec mentions this — it's a small clarification of the spec's `app/desktop/state.py` location, since it needs to be importable by the alert worker without depending on PyWebView).

- [ ] **Step 2.1: Write the failing test**

Create `tests/unit/test_desktop_state.py`:

```python
"""Unit tests for app.core.desktop_state — sensitivity read/write."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core import desktop_state


@pytest.fixture
def state_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect desktop_state to a tmp file for isolation."""
    p = tmp_path / "desktop_state.json"
    monkeypatch.setattr(desktop_state, "STATE_FILE", p)
    return p


def test_read_sensitivity_missing_file_returns_medium(state_file: Path) -> None:
    assert not state_file.exists()
    assert desktop_state.read_sensitivity() == "medium"


def test_read_sensitivity_valid_high(state_file: Path) -> None:
    state_file.write_text(json.dumps({"sensitivity_mode": "high"}))
    assert desktop_state.read_sensitivity() == "high"


def test_read_sensitivity_valid_low(state_file: Path) -> None:
    state_file.write_text(json.dumps({"sensitivity_mode": "low"}))
    assert desktop_state.read_sensitivity() == "low"


def test_read_sensitivity_invalid_value_returns_default(
    state_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    state_file.write_text(json.dumps({"sensitivity_mode": "extreme"}))
    with caplog.at_level("WARNING"):
        assert desktop_state.read_sensitivity() == "medium"
    assert any("invalid sensitivity_mode" in r.message for r in caplog.records)


def test_read_sensitivity_malformed_json_returns_default(
    state_file: Path, caplog: pytest.LogCaptureFixture
) -> None:
    state_file.write_text("{not json")
    with caplog.at_level("WARNING"):
        assert desktop_state.read_sensitivity() == "medium"
    assert any("malformed" in r.message.lower() for r in caplog.records)


def test_read_sensitivity_missing_key_returns_default(state_file: Path) -> None:
    state_file.write_text(json.dumps({"other_key": "value"}))
    assert desktop_state.read_sensitivity() == "medium"
```

- [ ] **Step 2.2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_desktop_state.py -xvs`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.desktop_state'`.

- [ ] **Step 2.3: Implement the module**

Create `app/core/desktop_state.py`:

```python
"""Read/write the desktop app's runtime state file.

The state file lives at ~/.signalstack/desktop_state.json and currently
holds a single field: sensitivity_mode (one of "high", "medium", "low").

Both the desktop app (writes via js_api) and the alert worker (reads
each loop iteration) use this module. Reads are cheap — a few hundred
bytes of JSON per iteration — and need no caching.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

SensitivityMode = Literal["high", "medium", "low"]
_VALID_MODES: frozenset[str] = frozenset({"high", "medium", "low"})
_DEFAULT_MODE: SensitivityMode = "medium"

STATE_FILE: Path = Path.home() / ".signalstack" / "desktop_state.json"


def read_sensitivity() -> SensitivityMode:
    """Return the current sensitivity mode, with safe fallback to medium.

    Falls back to "medium" if the file is missing, malformed, or contains
    an unknown mode value. Logs a warning in malformed/unknown cases.
    """
    if not STATE_FILE.exists():
        return _DEFAULT_MODE

    try:
        raw = STATE_FILE.read_text()
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("desktop_state.json is malformed (%s) — using default 'medium'", exc)
        return _DEFAULT_MODE
    except OSError as exc:
        log.warning("desktop_state.json could not be read (%s) — using default 'medium'", exc)
        return _DEFAULT_MODE

    mode = data.get("sensitivity_mode")
    if mode in _VALID_MODES:
        return mode  # type: ignore[return-value]

    if mode is not None:
        log.warning("invalid sensitivity_mode %r — using default 'medium'", mode)
    return _DEFAULT_MODE
```

- [ ] **Step 2.4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_desktop_state.py -xvs`

Expected: 6 tests pass.

- [ ] **Step 2.5: Lint check**

Run: `uv run ruff check app/core/desktop_state.py tests/unit/test_desktop_state.py`

Expected: no errors.

- [ ] **Step 2.6: Commit**

```bash
git add app/core/desktop_state.py tests/unit/test_desktop_state.py
git commit -m "feat(desktop_state): add sensitivity read with safe defaults"
```

---

## Task 3: Add sensitivity write (atomic)

**Files:**
- Modify: `app/core/desktop_state.py`
- Modify: `tests/unit/test_desktop_state.py`

- [ ] **Step 3.1: Add failing tests for write_sensitivity**

Append to `tests/unit/test_desktop_state.py`:

```python
def test_write_sensitivity_creates_file(state_file: Path) -> None:
    assert not state_file.exists()
    desktop_state.write_sensitivity("high")
    assert state_file.exists()
    assert json.loads(state_file.read_text())["sensitivity_mode"] == "high"


def test_write_sensitivity_creates_parent_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    nested = tmp_path / "nested" / "dir" / "state.json"
    monkeypatch.setattr(desktop_state, "STATE_FILE", nested)
    desktop_state.write_sensitivity("low")
    assert nested.exists()
    assert json.loads(nested.read_text())["sensitivity_mode"] == "low"


def test_write_sensitivity_overwrites_existing(state_file: Path) -> None:
    state_file.write_text(json.dumps({"sensitivity_mode": "high"}))
    desktop_state.write_sensitivity("low")
    assert json.loads(state_file.read_text())["sensitivity_mode"] == "low"


def test_write_sensitivity_rejects_invalid_mode(state_file: Path) -> None:
    with pytest.raises(ValueError, match="invalid sensitivity mode"):
        desktop_state.write_sensitivity("extreme")  # type: ignore[arg-type]
    assert not state_file.exists()  # nothing written on bad input


def test_write_sensitivity_no_tmp_file_left_on_success(state_file: Path) -> None:
    desktop_state.write_sensitivity("medium")
    siblings = list(state_file.parent.iterdir())
    # Only the final file should exist — no .tmp leftover
    assert siblings == [state_file]


def test_round_trip(state_file: Path) -> None:
    for mode in ("high", "medium", "low"):
        desktop_state.write_sensitivity(mode)
        assert desktop_state.read_sensitivity() == mode
```

- [ ] **Step 3.2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_desktop_state.py -xvs -k write`

Expected: 6 tests fail with `AttributeError: module 'app.core.desktop_state' has no attribute 'write_sensitivity'`.

- [ ] **Step 3.3: Implement write_sensitivity**

Append to `app/core/desktop_state.py`:

```python
def write_sensitivity(mode: SensitivityMode) -> None:
    """Atomically write the sensitivity mode to the state file.

    Writes to <STATE_FILE>.tmp first, then renames to the final path.
    This ensures readers (e.g., the alert worker on its next loop
    iteration) never see a half-written file.

    Raises ValueError for unknown modes — the caller (js_api) should
    have validated already, but this is a defensive check so a bad
    write never reaches disk.
    """
    if mode not in _VALID_MODES:
        raise ValueError(f"invalid sensitivity mode: {mode!r}")

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps({"sensitivity_mode": mode}, indent=2)

    fd, tmp_path = tempfile.mkstemp(
        prefix=STATE_FILE.name + ".",
        suffix=".tmp",
        dir=STATE_FILE.parent,
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(payload)
        os.replace(tmp_path, STATE_FILE)
    except Exception:
        # Clean up the tmp file if rename failed
        try:
            os.unlink(tmp_path)
        except FileNotFoundError:
            pass
        raise
```

- [ ] **Step 3.4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_desktop_state.py -xvs`

Expected: all 12 tests pass.

- [ ] **Step 3.5: Lint check**

Run: `uv run ruff check app/core/desktop_state.py tests/unit/test_desktop_state.py`

Expected: clean.

- [ ] **Step 3.6: Commit**

```bash
git add app/core/desktop_state.py tests/unit/test_desktop_state.py
git commit -m "feat(desktop_state): add atomic sensitivity write"
```

---

## Task 4: Sensitivity → grades helper

**Files:**
- Modify: `app/core/desktop_state.py`
- Modify: `tests/unit/test_desktop_state.py`

- [ ] **Step 4.1: Write the failing test**

Append to `tests/unit/test_desktop_state.py`:

```python
def test_sensitivity_to_grades_high() -> None:
    assert desktop_state.sensitivity_mode_to_grades("high") == frozenset({"A"})


def test_sensitivity_to_grades_medium() -> None:
    assert desktop_state.sensitivity_mode_to_grades("medium") == frozenset({"A", "B"})


def test_sensitivity_to_grades_low() -> None:
    assert desktop_state.sensitivity_mode_to_grades("low") == frozenset({"A", "B", "C"})


def test_sensitivity_to_grades_d_never_alerts() -> None:
    """D-grade should never appear in any sensitivity mode's allowed set."""
    for mode in ("high", "medium", "low"):
        assert "D" not in desktop_state.sensitivity_mode_to_grades(mode)
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_desktop_state.py::test_sensitivity_to_grades_high -xvs`

Expected: FAIL with `AttributeError: ... has no attribute 'sensitivity_mode_to_grades'`.

- [ ] **Step 4.3: Implement the helper**

Append to `app/core/desktop_state.py`:

```python
_GRADES_BY_MODE: dict[SensitivityMode, frozenset[str]] = {
    "high": frozenset({"A"}),
    "medium": frozenset({"A", "B"}),
    "low": frozenset({"A", "B", "C"}),
}


def sensitivity_mode_to_grades(mode: SensitivityMode) -> frozenset[str]:
    """Map a sensitivity mode to the set of alert grades it permits.

    D-grade is never alerted in any mode — that's already enforced
    upstream by the cap logic in app/signals/scoring.py.
    """
    return _GRADES_BY_MODE[mode]
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_desktop_state.py -xvs`

Expected: all 16 tests pass.

- [ ] **Step 4.5: Commit**

```bash
git add app/core/desktop_state.py tests/unit/test_desktop_state.py
git commit -m "feat(desktop_state): add sensitivity_mode_to_grades helper"
```

---

## Task 5: Wire sensitivity gate into AlertWorker

**Files:**
- Modify: `app/alerts/worker.py`
- Modify: `tests/unit/test_alert_worker.py`

**Approach decision:** Gated candidates have their `status` set from `"promoted"` to `"rejected"` and `rejection_reason` set to `f"sensitivity_gate:{mode}:grade_{grade}"`. The query at [worker.py:209](../../../app/alerts/worker.py#L209) only fetches `status == "promoted"`, so rejected ones won't be re-fetched. This satisfies the [CLAUDE.md](../../../CLAUDE.md) "record `rejection_reason` on every rejected `signal_candidate`" rule without needing a schema migration.

- [ ] **Step 5.1: Read the existing worker structure**

Run: `uv run cat app/alerts/worker.py | head -250` (or read the file).

Locate `run_once` (around line 121). The Phase A loop iterates over `_fetch_unalerted_candidates()` and builds an `Alert` for each. The gate goes at the **top** of that loop body, before `_fetch_news_summary`.

- [ ] **Step 5.2: Write the failing test (unit)**

Add to `tests/unit/test_alert_worker.py` (read existing file first to match its style and fixtures). The test exercises `run_once(db)` directly with a fake DB session.

If the existing test file uses an in-memory SQLite or mock DB, follow its pattern. If it uses a real `_test` DB via the `db` fixture from conftest, add this test there. Match the pattern of nearby tests.

```python
from datetime import UTC, datetime
from unittest.mock import MagicMock

from app.alerts.worker import AlertWorker
from app.db.models.signals import SignalCandidate


def test_alert_worker_high_mode_skips_b_grade(monkeypatch):
    """In high mode, only A-grade promoted candidates produce alerts."""
    monkeypatch.setattr(
        "app.alerts.worker.read_sensitivity", lambda: "high"
    )

    candidate_a = MagicMock(spec=SignalCandidate)
    candidate_a.id = 1
    candidate_a.grade = "A"
    candidate_a.status = "promoted"
    candidate_a.news_event_id = None

    candidate_b = MagicMock(spec=SignalCandidate)
    candidate_b.id = 2
    candidate_b.grade = "B"
    candidate_b.status = "promoted"
    candidate_b.news_event_id = None

    worker = AlertWorker(telegram_client=None)
    worker._fetch_unalerted_candidates = MagicMock(return_value=[candidate_a, candidate_b])
    worker._fetch_pending_alerts = MagicMock(return_value=[])
    worker._fetch_news_summary = MagicMock(return_value=None)
    worker._formatter.build = MagicMock(return_value=MagicMock(ticker="AAPL"))

    db = MagicMock()
    new_count = worker.run_once(db)

    # Only candidate A produces an alert
    assert new_count == 1
    # Candidate B is rejected with sensitivity_gate reason
    assert candidate_b.status == "rejected"
    assert candidate_b.rejection_reason == "sensitivity_gate:high:grade_B"
    assert candidate_b.rejected_at is not None
    # Candidate A is unchanged
    assert candidate_a.status == "promoted"


def test_alert_worker_low_mode_alerts_a_b_and_c(monkeypatch):
    """In low mode, A/B/C all alert; D is never reached (caps prevent it)."""
    monkeypatch.setattr(
        "app.alerts.worker.read_sensitivity", lambda: "low"
    )

    grades = ["A", "B", "C"]
    candidates = []
    for i, g in enumerate(grades):
        c = MagicMock(spec=SignalCandidate)
        c.id = i + 1
        c.grade = g
        c.status = "promoted"
        c.news_event_id = None
        candidates.append(c)

    worker = AlertWorker(telegram_client=None)
    worker._fetch_unalerted_candidates = MagicMock(return_value=candidates)
    worker._fetch_pending_alerts = MagicMock(return_value=[])
    worker._fetch_news_summary = MagicMock(return_value=None)
    worker._formatter.build = MagicMock(return_value=MagicMock(ticker="X"))

    new_count = worker.run_once(MagicMock())
    assert new_count == 3
    for c in candidates:
        assert c.status == "promoted"  # all admitted
        assert c.rejection_reason is None
```

- [ ] **Step 5.3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_alert_worker.py::test_alert_worker_high_mode_skips_b_grade tests/unit/test_alert_worker.py::test_alert_worker_low_mode_alerts_a_b_and_c -xvs`

Expected: FAIL — either `read_sensitivity` doesn't exist on the module yet, or the gate isn't applied.

- [ ] **Step 5.4: Add the import**

Edit `app/alerts/worker.py`. Add to the imports at the top:

```python
from app.core.desktop_state import read_sensitivity, sensitivity_mode_to_grades
```

- [ ] **Step 5.5: Add the gate to run_once**

In `run_once`, replace the Phase A block (currently around lines 128-137) with this gated version:

```python
        # Phase A: new candidates → new Alert rows
        candidates = self._fetch_unalerted_candidates(db, batch_size=self._batch_size)
        new_alerts: list[Alert] = []

        # Sensitivity gate: only allowed grades produce alerts.
        # Rejected candidates are marked with status='rejected' and a
        # sensitivity_gate rejection_reason, so they are not re-fetched
        # next cycle. The grade itself is unchanged — the actual emitted
        # Alert (when admitted) carries the candidate's true grade.
        mode = read_sensitivity()
        allowed_grades = sensitivity_mode_to_grades(mode)

        for candidate in candidates:
            if candidate.grade not in allowed_grades:
                candidate.status = "rejected"
                candidate.rejection_reason = (
                    f"sensitivity_gate:{mode}:grade_{candidate.grade}"
                )
                candidate.rejected_at = now
                continue

            news_summary = self._fetch_news_summary(db, candidate.news_event_id)
            alert = self._formatter.build(
                candidate, news_summary=news_summary, dry_run=self._dry_run
            )
            db.add(alert)
            new_alerts.append(alert)
```

- [ ] **Step 5.6: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_alert_worker.py -xvs`

Expected: all tests in the file pass (the two new ones plus any existing).

- [ ] **Step 5.7: Lint check**

Run: `uv run ruff check app/alerts/worker.py tests/unit/test_alert_worker.py`

Expected: clean.

- [ ] **Step 5.8: Commit**

```bash
git add app/alerts/worker.py tests/unit/test_alert_worker.py
git commit -m "feat(alerts): gate alerts by sensitivity mode

The alert worker now reads the sensitivity_mode from desktop_state
each loop iteration and only emits Alerts for candidates whose grade
is in the allowed set. Rejected candidates are marked with status
'rejected' and a 'sensitivity_gate:{mode}:grade_{grade}' reason."
```

---

## Task 6: Integration test — grade fidelity end-to-end

**Files:**
- Create: `tests/integration/test_alert_sensitivity_gate.py`

This test uses the real `_test` DB and exercises the full path: seed candidates → run worker → assert correct admit/reject + grade fidelity.

- [ ] **Step 6.1: Read existing integration test for pattern**

Run: `uv run cat tests/integration/test_label_worker.py | head -60` (any existing integration test will do; this just shows the fixture pattern).

- [ ] **Step 6.2: Write the failing integration test**

Create `tests/integration/test_alert_sensitivity_gate.py`:

```python
"""Integration test: sensitivity gate end-to-end with grade fidelity check."""
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
    p = tmp_path / "desktop_state.json"
    monkeypatch.setattr(desktop_state, "STATE_FILE", p)
    return p


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
        contract_expiration=None,
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
    db: Session, state_file: Path, mode: str, expected_grades: set[str]
) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"sensitivity_mode": mode}))

    seeds = [
        ("AAA", "A", 90.0),
        ("BBB", "B", 75.0),
        ("CCC", "C", 67.0),
    ]
    candidates = [_make_candidate(db, ticker=t, grade=g, score=s) for t, g, s in seeds]
    db.commit()

    worker = AlertWorker(telegram_client=None, dry_run=True)
    worker.run_once(db)
    db.commit()

    # Re-query to check what's in the DB after the run
    alerts = db.query(Alert).all()
    emitted_grades = {a.grade for a in alerts}
    assert emitted_grades == expected_grades, (
        f"mode={mode}: expected alerts for grades {expected_grades}, got {emitted_grades}"
    )

    # Grade fidelity: each emitted Alert carries the candidate's true grade
    for a in alerts:
        candidate = db.query(SignalCandidate).filter_by(id=a.signal_candidate_id).one()
        assert a.grade == candidate.grade, "alert grade must equal candidate grade"

    # Rejected candidates have correct rejection_reason
    rejected = db.query(SignalCandidate).filter_by(status="rejected").all()
    for c in rejected:
        assert c.rejection_reason is not None
        assert c.rejection_reason.startswith(f"sensitivity_gate:{mode}:grade_")
        assert c.rejected_at is not None
```

- [ ] **Step 6.3: Run the test**

Run: `uv run pytest tests/integration/test_alert_sensitivity_gate.py -xvs -m integration`

Expected: all three parametrized cases pass. If a fixture (`db`) isn't available, check `tests/conftest.py` for the actual fixture name and adjust — possibilities include `db`, `db_session`, or a session factory. Match what other integration tests use.

- [ ] **Step 6.4: Commit**

```bash
git add tests/integration/test_alert_sensitivity_gate.py
git commit -m "test(alerts): integration test for sensitivity gate + grade fidelity"
```

---

## Task 7: Scaffold `app/desktop/` module

**Files:**
- Create: `app/desktop/__init__.py`
- Create: `app/desktop/log_buffer.py`
- Create: `tests/unit/test_log_buffer.py`

The log buffer is the foundation — both subprocess controllers will pipe their output into it, and the JS API will read from it.

- [ ] **Step 7.1: Create the package**

Create `app/desktop/__init__.py` with one line:

```python
"""Desktop app: PyWebView wrapper that controls workers/API as subprocesses."""
```

- [ ] **Step 7.2: Write failing tests for log_buffer**

Create `tests/unit/test_log_buffer.py`:

```python
"""Unit tests for app.desktop.log_buffer."""
from __future__ import annotations

from app.desktop.log_buffer import LogBuffer


def test_appends_and_returns_lines() -> None:
    buf = LogBuffer(max_lines=10)
    buf.append("line 1")
    buf.append("line 2")
    assert buf.recent(50) == ["line 1", "line 2"]


def test_caps_at_max_lines() -> None:
    buf = LogBuffer(max_lines=3)
    for i in range(5):
        buf.append(f"line {i}")
    assert buf.recent(50) == ["line 2", "line 3", "line 4"]


def test_recent_returns_last_n() -> None:
    buf = LogBuffer(max_lines=100)
    for i in range(20):
        buf.append(f"line {i}")
    assert buf.recent(5) == [f"line {i}" for i in range(15, 20)]


def test_recent_when_buffer_smaller_than_n() -> None:
    buf = LogBuffer(max_lines=100)
    buf.append("only one")
    assert buf.recent(50) == ["only one"]


def test_thread_safe_under_concurrent_appends() -> None:
    """Smoke test: many threads appending should not raise or lose data integrity."""
    import threading

    buf = LogBuffer(max_lines=10000)

    def worker(start: int) -> None:
        for i in range(100):
            buf.append(f"t{start}-{i}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    lines = buf.recent(2000)
    assert len(lines) == 1000  # 10 threads × 100 lines each
```

- [ ] **Step 7.3: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_log_buffer.py -xvs`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.desktop.log_buffer'`.

- [ ] **Step 7.4: Implement LogBuffer**

Create `app/desktop/log_buffer.py`:

```python
"""Thread-safe ring buffer for subprocess stdout/stderr lines.

Both the workers and API subprocesses pipe their output into a shared
LogBuffer via reader threads. The Control tab in the UI fetches recent
lines via js_api.get_recent_logs() — read-only, no side effects.
"""
from __future__ import annotations

import threading
from collections import deque


class LogBuffer:
    """Bounded, thread-safe deque of log lines."""

    def __init__(self, max_lines: int = 200) -> None:
        self._buf: deque[str] = deque(maxlen=max_lines)
        self._lock = threading.Lock()

    def append(self, line: str) -> None:
        with self._lock:
            self._buf.append(line)

    def recent(self, n: int) -> list[str]:
        """Return up to the last n lines (oldest first)."""
        with self._lock:
            if n >= len(self._buf):
                return list(self._buf)
            return list(self._buf)[-n:]
```

- [ ] **Step 7.5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_log_buffer.py -xvs`

Expected: all 5 tests pass.

- [ ] **Step 7.6: Commit**

```bash
git add app/desktop/__init__.py app/desktop/log_buffer.py tests/unit/test_log_buffer.py
git commit -m "feat(desktop): scaffold module + thread-safe log buffer"
```

---

## Task 8: Subprocess controller — basic spawn/stop

**Files:**
- Create: `app/desktop/controller.py`
- Create: `tests/unit/test_controller.py`

This task covers the core subprocess lifecycle: spawn, terminate gracefully, kill on timeout, and surface status. Docker auto-launch and Postgres readiness come in Task 9.

- [ ] **Step 8.1: Write failing tests**

Create `tests/unit/test_controller.py`:

```python
"""Unit tests for app.desktop.controller — subprocess lifecycle."""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from app.desktop.controller import SubprocessController
from app.desktop.log_buffer import LogBuffer


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def buf() -> LogBuffer:
    return LogBuffer(max_lines=200)


def test_status_stopped_initially(buf: LogBuffer) -> None:
    ctrl = SubprocessController(
        name="probe",
        argv=[sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=REPO_ROOT,
        log_buffer=buf,
    )
    assert ctrl.status() == "stopped"


def test_start_then_running(buf: LogBuffer) -> None:
    ctrl = SubprocessController(
        name="probe",
        argv=[sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=REPO_ROOT,
        log_buffer=buf,
    )
    ctrl.start()
    try:
        time.sleep(0.5)  # let it start
        assert ctrl.status() == "running"
    finally:
        ctrl.stop(timeout=5.0)


def test_stop_terminates_cleanly(buf: LogBuffer) -> None:
    ctrl = SubprocessController(
        name="probe",
        argv=[sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=REPO_ROOT,
        log_buffer=buf,
    )
    ctrl.start()
    time.sleep(0.5)
    ctrl.stop(timeout=5.0)
    assert ctrl.status() == "stopped"


def test_stop_kills_unresponsive_process(buf: LogBuffer) -> None:
    """A process that ignores SIGTERM gets SIGKILLed after timeout."""
    ctrl = SubprocessController(
        name="ignorant",
        argv=[
            sys.executable,
            "-c",
            "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); time.sleep(60)",
        ],
        cwd=REPO_ROOT,
        log_buffer=buf,
    )
    ctrl.start()
    time.sleep(0.5)
    t0 = time.time()
    ctrl.stop(timeout=1.0)
    elapsed = time.time() - t0
    assert ctrl.status() == "stopped"
    assert 0.9 < elapsed < 3.0  # killed shortly after timeout


def test_logs_captured(buf: LogBuffer) -> None:
    ctrl = SubprocessController(
        name="echoer",
        argv=[sys.executable, "-u", "-c", "print('hello from probe'); import time; time.sleep(60)"],
        cwd=REPO_ROOT,
        log_buffer=buf,
    )
    ctrl.start()
    try:
        # Wait up to 2s for output
        for _ in range(20):
            if any("hello from probe" in line for line in buf.recent(50)):
                break
            time.sleep(0.1)
        assert any("hello from probe" in line for line in buf.recent(50))
    finally:
        ctrl.stop(timeout=2.0)


def test_double_start_is_idempotent(buf: LogBuffer) -> None:
    ctrl = SubprocessController(
        name="probe",
        argv=[sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=REPO_ROOT,
        log_buffer=buf,
    )
    ctrl.start()
    pid1 = ctrl._proc.pid  # type: ignore[union-attr]
    ctrl.start()  # second start should no-op
    pid2 = ctrl._proc.pid  # type: ignore[union-attr]
    try:
        assert pid1 == pid2
    finally:
        ctrl.stop(timeout=5.0)


def test_stop_when_not_running_is_safe(buf: LogBuffer) -> None:
    ctrl = SubprocessController(
        name="probe",
        argv=[sys.executable, "-c", "pass"],
        cwd=REPO_ROOT,
        log_buffer=buf,
    )
    ctrl.stop(timeout=1.0)  # should not raise
    assert ctrl.status() == "stopped"
```

- [ ] **Step 8.2: Run to verify failure**

Run: `uv run pytest tests/unit/test_controller.py -xvs`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.desktop.controller'`.

- [ ] **Step 8.3: Implement SubprocessController**

Create `app/desktop/controller.py`:

```python
"""Manage a single long-running subprocess (workers or uvicorn).

Lifecycle:
    stopped -> start() -> running -> stop() -> stopped

A reader thread continuously consumes stdout (merged with stderr) and
pushes each line into a shared LogBuffer. The status is derived from
poll() on the underlying Popen.
"""
from __future__ import annotations

import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Literal

from app.desktop.log_buffer import LogBuffer

log = logging.getLogger(__name__)

Status = Literal["stopped", "running"]


class SubprocessController:
    """Owns one subprocess: spawn, terminate, log capture."""

    def __init__(
        self,
        *,
        name: str,
        argv: list[str],
        cwd: Path,
        log_buffer: LogBuffer,
        env_extra: dict[str, str] | None = None,
    ) -> None:
        self._name = name
        self._argv = argv
        self._cwd = cwd
        self._log = log_buffer
        self._env_extra = env_extra or {}
        self._proc: subprocess.Popen[str] | None = None
        self._reader_thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                return  # already running

            env = os.environ.copy()
            env["PYTHONUNBUFFERED"] = "1"  # ensure subprocess writes lines promptly
            env.update(self._env_extra)

            self._log.append(f"[{self._name}] starting: {' '.join(self._argv)}")
            self._proc = subprocess.Popen(
                self._argv,
                cwd=str(self._cwd),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            self._reader_thread = threading.Thread(
                target=self._read_output,
                args=(self._proc,),
                daemon=True,
                name=f"reader-{self._name}",
            )
            self._reader_thread.start()

    def stop(self, *, timeout: float = 10.0) -> None:
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                self._proc = None
                return

            self._log.append(f"[{self._name}] stopping…")
            try:
                proc.terminate()
            except ProcessLookupError:
                self._proc = None
                return

            try:
                proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._log.append(
                    f"[{self._name}] did not exit in {timeout}s — sending SIGKILL"
                )
                try:
                    proc.kill()
                    proc.wait(timeout=2.0)
                except (ProcessLookupError, subprocess.TimeoutExpired) as exc:
                    log.warning("Final kill of %s failed: %s", self._name, exc)

            self._log.append(f"[{self._name}] stopped (exit={proc.returncode})")
            self._proc = None

    def status(self) -> Status:
        proc = self._proc
        if proc is None:
            return "stopped"
        if proc.poll() is None:
            return "running"
        return "stopped"

    def _read_output(self, proc: subprocess.Popen[str]) -> None:
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                self._log.append(f"[{self._name}] {line.rstrip()}")
        except Exception as exc:  # noqa: BLE001 — defensive, isolate reader from owner
            log.warning("reader for %s crashed: %s", self._name, exc)
        finally:
            # Catch the final exit so status() reflects it on next poll
            proc.wait()
```

Helper to keep the test from drifting if you change Popen signature: leave `_proc` exposed (with leading underscore). The test imports it but with a `# type: ignore` so it's clearly an intentional private peek.

- [ ] **Step 8.4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_controller.py -xvs`

Expected: all 7 tests pass. Tests take ~5-10 seconds total because of subprocess wait times.

- [ ] **Step 8.5: Lint check**

Run: `uv run ruff check app/desktop/controller.py tests/unit/test_controller.py`

Expected: clean.

- [ ] **Step 8.6: Commit**

```bash
git add app/desktop/controller.py tests/unit/test_controller.py
git commit -m "feat(desktop): SubprocessController with graceful stop and log capture"
```

---

## Task 9: Docker / Postgres readiness helpers

**Files:**
- Create: `app/desktop/system_probes.py`
- Create: `tests/unit/test_system_probes.py`

These are pure helper functions: check Docker daemon, launch Docker Desktop on macOS, wait for it, check/start the Postgres container. Each is testable in isolation (with subprocess mocks).

- [ ] **Step 9.1: Write failing tests**

Create `tests/unit/test_system_probes.py`:

```python
"""Unit tests for app.desktop.system_probes."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.desktop import system_probes


def test_docker_running_when_info_succeeds() -> None:
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        assert system_probes.docker_running() is True


def test_docker_not_running_when_info_fails() -> None:
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=1)
        assert system_probes.docker_running() is False


def test_docker_not_running_when_command_missing() -> None:
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert system_probes.docker_running() is False


def test_docker_desktop_installed_true(tmp_path, monkeypatch):
    fake_app = tmp_path / "Docker.app"
    fake_app.mkdir()
    monkeypatch.setattr(system_probes, "DOCKER_APP_PATH", fake_app)
    assert system_probes.docker_desktop_installed() is True


def test_docker_desktop_installed_false(tmp_path, monkeypatch):
    monkeypatch.setattr(system_probes, "DOCKER_APP_PATH", tmp_path / "missing.app")
    assert system_probes.docker_desktop_installed() is False


def test_launch_docker_desktop_invokes_open() -> None:
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        system_probes.launch_docker_desktop()
        run.assert_called_once()
        args = run.call_args.args[0]
        assert args[:2] == ["open", "-a"]
        assert args[2] == "Docker"


def test_wait_for_docker_returns_true_when_already_up() -> None:
    with patch.object(system_probes, "docker_running", return_value=True):
        assert system_probes.wait_for_docker(timeout=5.0, poll_interval=0.1) is True


def test_wait_for_docker_returns_false_on_timeout() -> None:
    with patch.object(system_probes, "docker_running", return_value=False):
        assert system_probes.wait_for_docker(timeout=0.5, poll_interval=0.1) is False


def test_wait_for_docker_succeeds_after_a_few_polls() -> None:
    calls = {"n": 0}

    def fake_running() -> bool:
        calls["n"] += 1
        return calls["n"] >= 3

    with patch.object(system_probes, "docker_running", side_effect=fake_running):
        assert system_probes.wait_for_docker(timeout=5.0, poll_interval=0.1) is True
    assert calls["n"] >= 3


def test_postgres_running_parses_compose_ps() -> None:
    fake_output = '[{"Service":"postgres","State":"running","Health":"healthy"}]\n'
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout=fake_output)
        assert system_probes.postgres_running() is True


def test_postgres_running_false_when_state_not_running() -> None:
    fake_output = '[{"Service":"postgres","State":"exited"}]\n'
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=0, stdout=fake_output)
        assert system_probes.postgres_running() is False


def test_postgres_running_false_when_compose_fails() -> None:
    with patch("subprocess.run") as run:
        run.return_value = MagicMock(returncode=1, stdout="")
        assert system_probes.postgres_running() is False
```

- [ ] **Step 9.2: Run to verify failure**

Run: `uv run pytest tests/unit/test_system_probes.py -xvs`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 9.3: Implement system_probes.py**

Create `app/desktop/system_probes.py`:

```python
"""Helpers to probe and launch Docker / Postgres for the desktop app.

All functions are designed to be safe to call from any thread and to
fail gracefully (return False rather than raise) when underlying
commands are missing or fail.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path

log = logging.getLogger(__name__)

DOCKER_APP_PATH: Path = Path("/Applications/Docker.app")


def docker_running() -> bool:
    """Return True if `docker info` succeeds (the daemon is up)."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=2.0,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def docker_desktop_installed() -> bool:
    """Return True if /Applications/Docker.app exists."""
    return DOCKER_APP_PATH.exists()


def launch_docker_desktop() -> None:
    """Launch Docker Desktop on macOS (`open -a Docker`).

    Returns immediately — the daemon takes additional time to be ready.
    Caller should follow up with wait_for_docker().
    """
    subprocess.run(["open", "-a", "Docker"], check=False)


def wait_for_docker(*, timeout: float = 60.0, poll_interval: float = 2.0) -> bool:
    """Poll docker_running() until it returns True or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if docker_running():
            return True
        time.sleep(poll_interval)
    return False


def postgres_running(*, compose_dir: Path | None = None) -> bool:
    """Return True if `docker compose ps postgres` reports state=running."""
    cmd = ["docker", "compose", "ps", "postgres", "--format", "json"]
    cwd = str(compose_dir) if compose_dir else None
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=5.0, cwd=cwd
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    if result.returncode != 0 or not result.stdout.strip():
        return False
    try:
        # Newer compose versions emit a JSON array; older versions emit JSONL.
        stripped = result.stdout.strip()
        if stripped.startswith("["):
            entries = json.loads(stripped)
        else:
            entries = [json.loads(line) for line in stripped.splitlines() if line.strip()]
    except json.JSONDecodeError:
        return False
    return any(e.get("State") == "running" for e in entries)


def start_postgres(*, compose_dir: Path) -> bool:
    """Run `docker compose up -d postgres`. Returns True on success."""
    try:
        result = subprocess.run(
            ["docker", "compose", "up", "-d", "postgres"],
            cwd=str(compose_dir),
            capture_output=True,
            text=True,
            timeout=30.0,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        log.warning("start_postgres failed: %s", exc)
        return False
    if result.returncode != 0:
        log.warning("docker compose up returned %d: %s", result.returncode, result.stderr)
        return False
    return True


def wait_for_postgres(*, compose_dir: Path, timeout: float = 10.0, poll_interval: float = 0.5) -> bool:
    """Poll postgres_running() until True or timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if postgres_running(compose_dir=compose_dir):
            return True
        time.sleep(poll_interval)
    return False
```

- [ ] **Step 9.4: Run tests**

Run: `uv run pytest tests/unit/test_system_probes.py -xvs`

Expected: all 12 tests pass. (`test_wait_for_docker_returns_false_on_timeout` takes ~0.5s; that's why poll_interval is small in the test.)

- [ ] **Step 9.5: Lint check + format**

Run: `uv run ruff check app/desktop/system_probes.py tests/unit/test_system_probes.py`

Expected: clean.

- [ ] **Step 9.6: Commit**

```bash
git add app/desktop/system_probes.py tests/unit/test_system_probes.py
git commit -m "feat(desktop): Docker/Postgres probes with auto-launch helper"
```

---

## Task 10: System orchestrator — combine controllers + probes

**Files:**
- Create: `app/desktop/system.py`
- Create: `tests/unit/test_system.py`

This is the higher-level "Start System / Stop System" coordinator that the JS API will call. It composes the SubprocessControllers (workers, API) and the system_probes (Docker, Postgres) into the documented Start sequence from the spec §7.

- [ ] **Step 10.1: Write failing test (orchestration only — pure logic, mocks for everything I/O)**

Create `tests/unit/test_system.py`:

```python
"""Unit tests for app.desktop.system — Start/Stop orchestration."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.desktop.log_buffer import LogBuffer
from app.desktop.system import StartResult, SystemController


@pytest.fixture
def buf() -> LogBuffer:
    return LogBuffer(max_lines=200)


def _make_controller(buf: LogBuffer) -> SystemController:
    return SystemController(repo_root=MagicMock(), log_buffer=buf)


def test_start_when_docker_already_up_and_postgres_up(buf: LogBuffer) -> None:
    ctrl = _make_controller(buf)
    with (
        patch("app.desktop.system.docker_running", return_value=True),
        patch("app.desktop.system.postgres_running", return_value=True),
        patch.object(ctrl._workers, "start") as ws,
        patch.object(ctrl._api, "start") as as_,
    ):
        result = ctrl.start()
    assert result == StartResult(ok=True, error=None)
    ws.assert_called_once()
    as_.assert_called_once()


def test_start_aborts_when_docker_not_installed(buf: LogBuffer) -> None:
    ctrl = _make_controller(buf)
    with (
        patch("app.desktop.system.docker_running", return_value=False),
        patch("app.desktop.system.docker_desktop_installed", return_value=False),
    ):
        result = ctrl.start()
    assert result.ok is False
    assert "not installed" in (result.error or "").lower()


def test_start_launches_docker_when_not_running(buf: LogBuffer) -> None:
    ctrl = _make_controller(buf)
    with (
        patch("app.desktop.system.docker_running", return_value=False),
        patch("app.desktop.system.docker_desktop_installed", return_value=True),
        patch("app.desktop.system.launch_docker_desktop") as launch,
        patch("app.desktop.system.wait_for_docker", return_value=True),
        patch("app.desktop.system.start_postgres", return_value=True),
        patch("app.desktop.system.wait_for_postgres", return_value=True),
        patch.object(ctrl._workers, "start"),
        patch.object(ctrl._api, "start"),
    ):
        result = ctrl.start()
    assert result.ok is True
    launch.assert_called_once()


def test_start_aborts_when_docker_wait_times_out(buf: LogBuffer) -> None:
    ctrl = _make_controller(buf)
    with (
        patch("app.desktop.system.docker_running", return_value=False),
        patch("app.desktop.system.docker_desktop_installed", return_value=True),
        patch("app.desktop.system.launch_docker_desktop"),
        patch("app.desktop.system.wait_for_docker", return_value=False),
    ):
        result = ctrl.start()
    assert result.ok is False
    assert "didn't start in time" in (result.error or "")


def test_start_aborts_when_postgres_fails(buf: LogBuffer) -> None:
    ctrl = _make_controller(buf)
    with (
        patch("app.desktop.system.docker_running", return_value=True),
        patch("app.desktop.system.postgres_running", return_value=False),
        patch("app.desktop.system.start_postgres", return_value=False),
    ):
        result = ctrl.start()
    assert result.ok is False
    assert "postgres" in (result.error or "").lower()


def test_stop_terminates_both_subprocesses(buf: LogBuffer) -> None:
    ctrl = _make_controller(buf)
    with patch.object(ctrl._workers, "stop") as ws, patch.object(ctrl._api, "stop") as as_:
        ctrl.stop()
    ws.assert_called_once()
    as_.assert_called_once()


def test_status_combines_components(buf: LogBuffer) -> None:
    ctrl = _make_controller(buf)
    with (
        patch("app.desktop.system.docker_running", return_value=True),
        patch("app.desktop.system.postgres_running", return_value=True),
        patch.object(ctrl._workers, "status", return_value="running"),
        patch.object(ctrl._api, "status", return_value="stopped"),
    ):
        s = ctrl.status()
    assert s == {
        "docker": "running",
        "postgres": "running",
        "workers": "running",
        "api": "stopped",
    }
```

- [ ] **Step 10.2: Run to verify failure**

Run: `uv run pytest tests/unit/test_system.py -xvs`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 10.3: Implement system.py**

Create `app/desktop/system.py`:

```python
"""High-level Start / Stop orchestration for the desktop app.

Exposes a SystemController that the JS API holds and calls. This is
where the spec's documented Start sequence lives:

  1. Check docker_running() — if true, skip ahead.
  2. Check docker_desktop_installed() — if false, abort with clear error.
  3. launch_docker_desktop() + wait_for_docker(60s).
  4. start_postgres() + wait_for_postgres(10s).
  5. Spawn API subprocess (uvicorn).
  6. Spawn workers subprocess (python -m app.main_workers).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.desktop.controller import SubprocessController
from app.desktop.log_buffer import LogBuffer
from app.desktop.system_probes import (
    docker_desktop_installed,
    docker_running,
    launch_docker_desktop,
    postgres_running,
    start_postgres,
    wait_for_docker,
    wait_for_postgres,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StartResult:
    ok: bool
    error: str | None


class SystemController:
    """Coordinates Docker, Postgres, workers, and API."""

    def __init__(self, *, repo_root: Path, log_buffer: LogBuffer) -> None:
        self._repo_root = repo_root
        self._log = log_buffer
        self._last_started_at: datetime | None = None

        self._api = SubprocessController(
            name="api",
            argv=[
                "uv",
                "run",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "8000",
            ],
            cwd=repo_root,
            log_buffer=log_buffer,
        )
        self._workers = SubprocessController(
            name="workers",
            argv=["uv", "run", "python", "-m", "app.main_workers"],
            cwd=repo_root,
            log_buffer=log_buffer,
        )

    @property
    def last_started_at(self) -> datetime | None:
        return self._last_started_at

    def start(self) -> StartResult:
        # Step 1-3: Docker
        if not docker_running():
            if not docker_desktop_installed():
                return StartResult(
                    ok=False,
                    error="Docker Desktop is not installed.",
                )
            self._log.append("[system] launching Docker Desktop…")
            launch_docker_desktop()
            if not wait_for_docker(timeout=60.0, poll_interval=2.0):
                return StartResult(
                    ok=False,
                    error="Docker Desktop didn't start in time. Open it manually and try again.",
                )

        # Step 4: Postgres
        if not postgres_running():
            self._log.append("[system] starting Postgres…")
            if not start_postgres(compose_dir=self._repo_root):
                return StartResult(ok=False, error="Postgres failed to start.")
            if not wait_for_postgres(compose_dir=self._repo_root, timeout=10.0):
                return StartResult(ok=False, error="Postgres didn't become ready in time.")

        # Step 5: API
        self._api.start()
        # Step 6: Workers
        self._workers.start()

        self._last_started_at = datetime.now(UTC)
        return StartResult(ok=True, error=None)

    def stop(self) -> None:
        self._workers.stop(timeout=10.0)
        self._api.stop(timeout=10.0)

    def status(self) -> dict[str, str]:
        return {
            "docker": "running" if docker_running() else "stopped",
            "postgres": "running" if postgres_running() else "stopped",
            "workers": self._workers.status(),
            "api": self._api.status(),
        }
```

- [ ] **Step 10.4: Run tests**

Run: `uv run pytest tests/unit/test_system.py -xvs`

Expected: all 7 tests pass.

- [ ] **Step 10.5: Lint check**

Run: `uv run ruff check app/desktop/system.py tests/unit/test_system.py`

Expected: clean.

- [ ] **Step 10.6: Commit**

```bash
git add app/desktop/system.py tests/unit/test_system.py
git commit -m "feat(desktop): SystemController orchestrating Docker, Postgres, workers, API"
```

---

## Task 11: JavaScript API surface

**Files:**
- Create: `app/desktop/js_api.py`
- Create: `tests/unit/test_js_api.py`

This is the thin layer that PyWebView exposes to the webview JavaScript. Each method here is callable from JS as `pywebview.api.<name>(args)`. Validation happens here so the system layer can stay clean.

- [ ] **Step 11.1: Write failing tests**

Create `tests/unit/test_js_api.py`:

```python
"""Unit tests for app.desktop.js_api."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.desktop.js_api import JsApi
from app.desktop.log_buffer import LogBuffer
from app.desktop.system import StartResult


@pytest.fixture
def js_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> JsApi:
    state_path = tmp_path / "desktop_state.json"
    from app.core import desktop_state
    monkeypatch.setattr(desktop_state, "STATE_FILE", state_path)

    buf = LogBuffer(max_lines=200)
    system = MagicMock()
    return JsApi(system=system, log_buffer=buf)


def test_get_status_delegates_to_system(js_api: JsApi) -> None:
    js_api._system.status.return_value = {
        "docker": "running",
        "postgres": "running",
        "workers": "stopped",
        "api": "stopped",
    }
    assert js_api.get_status()["workers"] == "stopped"


def test_start_system_returns_dict_on_success(js_api: JsApi) -> None:
    js_api._system.start.return_value = StartResult(ok=True, error=None)
    result = js_api.start_system()
    assert result == {"ok": True, "error": None}


def test_start_system_returns_error_on_failure(js_api: JsApi) -> None:
    js_api._system.start.return_value = StartResult(ok=False, error="Docker not installed.")
    result = js_api.start_system()
    assert result == {"ok": False, "error": "Docker not installed."}


def test_stop_system_calls_system_stop(js_api: JsApi) -> None:
    js_api.stop_system()
    js_api._system.stop.assert_called_once()


def test_get_recent_logs_returns_lines(js_api: JsApi) -> None:
    js_api._log.append("first")
    js_api._log.append("second")
    assert js_api.get_recent_logs(50) == ["first", "second"]


def test_get_sensitivity_returns_default_when_unset(js_api: JsApi) -> None:
    assert js_api.get_sensitivity() == "medium"


def test_set_sensitivity_writes_and_returns_new_value(js_api: JsApi) -> None:
    result = js_api.set_sensitivity("high")
    assert result == {"ok": True, "mode": "high"}
    assert js_api.get_sensitivity() == "high"


def test_set_sensitivity_rejects_unknown_value(js_api: JsApi) -> None:
    result = js_api.set_sensitivity("extreme")
    assert result["ok"] is False
    assert "invalid" in result["error"].lower()
    # Original value unchanged
    assert js_api.get_sensitivity() == "medium"
```

- [ ] **Step 11.2: Run to verify failure**

Run: `uv run pytest tests/unit/test_js_api.py -xvs`

Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 11.3: Implement js_api.py**

Create `app/desktop/js_api.py`:

```python
"""JavaScript-callable API exposed to the PyWebView frontend.

PyWebView automatically converts public methods on this object into
`pywebview.api.<name>()` callables in JS. All return values must be
JSON-serializable. Errors are returned as dicts with ok=False rather
than raised — the JS side cannot easily catch Python exceptions.
"""
from __future__ import annotations

import logging

from app.core.desktop_state import (
    SensitivityMode,
    read_sensitivity,
    write_sensitivity,
)
from app.desktop.log_buffer import LogBuffer
from app.desktop.system import SystemController

log = logging.getLogger(__name__)


class JsApi:
    """Public surface called from the dashboard JS via pywebview.api."""

    def __init__(self, *, system: SystemController, log_buffer: LogBuffer) -> None:
        self._system = system
        self._log = log_buffer

    # --- System control ------------------------------------------------

    def start_system(self) -> dict[str, object]:
        result = self._system.start()
        return {"ok": result.ok, "error": result.error}

    def stop_system(self) -> dict[str, object]:
        self._system.stop()
        return {"ok": True, "error": None}

    def get_status(self) -> dict[str, str]:
        return self._system.status()

    def get_recent_logs(self, n: int = 50) -> list[str]:
        return self._log.recent(int(n))

    def get_last_started_at(self) -> str | None:
        ts = self._system.last_started_at
        return ts.isoformat() if ts else None

    # --- Sensitivity ---------------------------------------------------

    def get_sensitivity(self) -> SensitivityMode:
        return read_sensitivity()

    def set_sensitivity(self, mode: str) -> dict[str, object]:
        if mode not in ("high", "medium", "low"):
            return {
                "ok": False,
                "error": f"invalid sensitivity mode: {mode!r}",
                "mode": read_sensitivity(),
            }
        try:
            write_sensitivity(mode)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 — must surface to JS, not crash window
            log.exception("failed to write sensitivity")
            return {"ok": False, "error": str(exc), "mode": read_sensitivity()}
        return {"ok": True, "mode": mode, "error": None}
```

- [ ] **Step 11.4: Run tests**

Run: `uv run pytest tests/unit/test_js_api.py -xvs`

Expected: all 8 tests pass.

- [ ] **Step 11.5: Lint check**

Run: `uv run ruff check app/desktop/js_api.py tests/unit/test_js_api.py`

Expected: clean.

- [ ] **Step 11.6: Commit**

```bash
git add app/desktop/js_api.py tests/unit/test_js_api.py
git commit -m "feat(desktop): JsApi exposing start/stop/status/logs/sensitivity"
```

---

## Task 12: Single-instance lock

**Files:**
- Create: `app/desktop/instance_lock.py`
- Create: `tests/unit/test_instance_lock.py`

A small file lock prevents two SignalStack windows from running simultaneously (which would collide on port 8000 and other shared resources).

- [ ] **Step 12.1: Write failing tests**

Create `tests/unit/test_instance_lock.py`:

```python
"""Unit tests for app.desktop.instance_lock."""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.desktop.instance_lock import InstanceLockError, acquire_lock


@pytest.fixture
def lock_path(tmp_path: Path) -> Path:
    return tmp_path / "desktop.lock"


def test_acquire_creates_lock_file(lock_path: Path) -> None:
    with acquire_lock(lock_path):
        assert lock_path.exists()
        # Lock file contains a PID (an integer)
        assert lock_path.read_text().strip().isdigit()


def test_lock_released_on_context_exit(lock_path: Path) -> None:
    with acquire_lock(lock_path):
        assert lock_path.exists()
    assert not lock_path.exists()


def test_second_acquire_when_first_pid_alive_raises(lock_path: Path) -> None:
    lock_path.write_text(str(os.getpid()))
    # os.getpid() is alive — should be detected as a real conflict
    with pytest.raises(InstanceLockError, match="already running"):
        with acquire_lock(lock_path):
            pass


def test_second_acquire_when_first_pid_dead_steals_lock(lock_path: Path) -> None:
    # Use a PID that's almost certainly not alive
    lock_path.write_text("999999")
    with patch("app.desktop.instance_lock._pid_alive", return_value=False):
        with acquire_lock(lock_path) as p:
            assert p == lock_path
            assert lock_path.read_text().strip() == str(os.getpid())


def test_lock_creates_parent_directory(tmp_path: Path) -> None:
    lock_path = tmp_path / "deep" / "path" / "desktop.lock"
    with acquire_lock(lock_path):
        assert lock_path.exists()
```

- [ ] **Step 12.2: Run to verify failure**

Run: `uv run pytest tests/unit/test_instance_lock.py -xvs`

Expected: FAIL — module doesn't exist.

- [ ] **Step 12.3: Implement instance_lock.py**

Create `app/desktop/instance_lock.py`:

```python
"""Single-instance lock for the SignalStack desktop app.

Prevents two SignalStack windows from running at once (which would
collide on port 8000 and other shared state).
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class InstanceLockError(RuntimeError):
    """Raised when another instance already holds the lock."""


def _pid_alive(pid: int) -> bool:
    """Return True if a process with this PID is currently alive."""
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    except OSError:
        return False
    return True


@contextmanager
def acquire_lock(lock_path: Path) -> Iterator[Path]:
    """Acquire an exclusive lock file. Releases on context exit.

    If the lock file exists and contains an alive PID, raises
    InstanceLockError. If it exists but the PID is dead (stale lock),
    the lock is silently stolen — the previous instance crashed.
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    if lock_path.exists():
        try:
            existing = int(lock_path.read_text().strip() or "0")
        except ValueError:
            existing = 0
        if _pid_alive(existing):
            raise InstanceLockError(
                f"SignalStack is already running (PID {existing})."
            )
        # Stale lock — fall through and overwrite

    lock_path.write_text(str(os.getpid()))
    try:
        yield lock_path
    finally:
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
```

- [ ] **Step 12.4: Run tests**

Run: `uv run pytest tests/unit/test_instance_lock.py -xvs`

Expected: all 5 tests pass.

- [ ] **Step 12.5: Commit**

```bash
git add app/desktop/instance_lock.py tests/unit/test_instance_lock.py
git commit -m "feat(desktop): single-instance lock with stale-lock detection"
```

---

## Task 13: Window + entry point

**Files:**
- Create: `app/desktop/window.py`
- Create: `app/desktop/__main__.py`

These are the integration glue. Light on logic, heavy on wiring. No automated tests — they're verified in the manual smoke test.

- [ ] **Step 13.1: Implement window.py**

Create `app/desktop/window.py`:

```python
"""Build and run the PyWebView window for SignalStack.

The window loads web/SignalStack.html and exposes the JsApi as
`pywebview.api`. PyWebView's built-in http_server serves the file
over a local origin so the existing API CORS rules can match it
(see Task 14).
"""
from __future__ import annotations

import logging
from pathlib import Path

import webview

from app.desktop.js_api import JsApi
from app.desktop.log_buffer import LogBuffer
from app.desktop.system import SystemController

log = logging.getLogger(__name__)


def run(*, repo_root: Path) -> None:
    """Open the SignalStack desktop window. Blocks until the window closes."""
    html_path = repo_root / "web" / "SignalStack.html"
    if not html_path.exists():
        raise FileNotFoundError(f"Dashboard HTML missing: {html_path}")

    log_buffer = LogBuffer(max_lines=200)
    system = SystemController(repo_root=repo_root, log_buffer=log_buffer)
    js_api = JsApi(system=system, log_buffer=log_buffer)

    window = webview.create_window(
        title="SignalStack",
        url=str(html_path),
        js_api=js_api,
        width=1200,
        height=800,
        resizable=True,
    )

    def _on_closing() -> bool:
        # Stop subprocesses before the window exits so nothing is orphaned.
        log.info("Window closing — stopping system")
        try:
            system.stop()
        except Exception:  # noqa: BLE001 — log and proceed; closing must not hang
            log.exception("Error stopping system on window close")
        return True

    window.events.closing += _on_closing

    # http_server=True serves the HTML over http://localhost:<random_port>
    # which avoids file:// CORS issues with API calls to localhost:8000.
    webview.start(http_server=True)
```

- [ ] **Step 13.2: Implement __main__.py**

Create `app/desktop/__main__.py`:

```python
"""Entry point: `uv run python -m app.desktop`."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from app.desktop.instance_lock import InstanceLockError, acquire_lock
from app.desktop.window import run

log = logging.getLogger(__name__)


def _repo_root() -> Path:
    # __file__ -> app/desktop/__main__.py; parents[2] -> repo root
    return Path(__file__).resolve().parents[2]


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    lock_path = Path.home() / ".signalstack" / "desktop.lock"
    try:
        with acquire_lock(lock_path):
            run(repo_root=_repo_root())
    except InstanceLockError as exc:
        print(f"SignalStack: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 13.3: Smoke check the launch path (does not run the GUI yet — Task 14 covers CORS, Task 15+ build the new tabs)**

Run: `uv run python -c "from app.desktop.window import run; print('imports ok')"`

Expected: prints `imports ok`. Any ImportError indicates a missing piece.

Run: `uv run python -m app.desktop --help` *(this won't actually accept --help; it'll just try to launch. If it tries to launch and you see a window, close it. If it errors before launching, fix the error.)*

A more conservative check: `uv run python -c "import app.desktop.__main__ as m; print(m._repo_root())"` — should print the repo root path.

- [ ] **Step 13.4: Lint check**

Run: `uv run ruff check app/desktop/`

Expected: clean.

- [ ] **Step 13.5: Commit**

```bash
git add app/desktop/window.py app/desktop/__main__.py
git commit -m "feat(desktop): window + entry point with single-instance lock and clean shutdown"
```

---

## Task 14: Update CORS to allow webview origin

**Files:**
- Modify: `app/main.py`
- Create: `tests/unit/test_cors_webview.py`

PyWebView's `http_server=True` serves files at `http://127.0.0.1:<random>` (a different port each launch). The existing CORS allow-list only includes ports 3000. We need to allow any local origin.

- [ ] **Step 14.1: Inspect current CORS config**

Read `app/main.py` lines 12-25 (or wherever `add_middleware(CORSMiddleware, ...)` is). Note the existing `allow_origins` list.

- [ ] **Step 14.2: Write failing test**

Create `tests/unit/test_cors_webview.py`:

```python
"""Verify CORS allows the webview origin pattern.

PyWebView serves the dashboard at http://127.0.0.1:<random_port>. The
API must accept those origins so the embedded JS can call /api/v1/...
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_cors_allows_localhost_random_port() -> None:
    response = client.options(
        "/api/v1/alerts",
        headers={
            "Origin": "http://127.0.0.1:54321",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") in (
        "http://127.0.0.1:54321",
        "*",
    )


def test_cors_still_allows_existing_dev_server() -> None:
    response = client.options(
        "/api/v1/alerts",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") in (
        "http://localhost:3000",
        "*",
    )
```

- [ ] **Step 14.3: Run to verify failure**

Run: `uv run pytest tests/unit/test_cors_webview.py -xvs`

Expected: FAIL — the random-port test rejects the origin.

- [ ] **Step 14.4: Update CORS config**

Edit `app/main.py`. Replace the existing CORSMiddleware setup with one that uses a regex matching any localhost/127.0.0.1 origin on any port:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

This replaces the `allow_origins=[...]` list with a regex that covers both the existing localhost:3000 dev origin and the PyWebView random-port origin, while still rejecting external origins.

- [ ] **Step 14.5: Run tests**

Run: `uv run pytest tests/unit/test_cors_webview.py -xvs`

Expected: both tests pass.

- [ ] **Step 14.6: Run the full test suite to make sure nothing else broke**

Run: `uv run pytest tests/unit -xvs`

Expected: all tests pass.

- [ ] **Step 14.7: Commit**

```bash
git add app/main.py tests/unit/test_cors_webview.py
git commit -m "fix(api): broaden CORS to any localhost port for webview embed"
```

---

## Task 15: Add Control sidebar entry

**Files:**
- Modify: `web/signalstack/Sidebar.jsx`

**Note:** [`web/signalstack/Sidebar.jsx`](../../../web/signalstack/Sidebar.jsx) already has a `{ id: "settings", label: "Settings", icon: "⚙" }` entry at the end of `NAV_ITEMS`, and [`web/SignalStack.html:118`](../../../web/SignalStack.html#L118) already routes `case "settings": return <Settings />;` — but `Settings.jsx` doesn't exist yet. So we only need to add a Control entry; Settings is already wired (we just need to create the component file in Task 16).

- [ ] **Step 15.1: Add the Control entry to NAV_ITEMS**

Edit `web/signalstack/Sidebar.jsx`. The current `NAV_ITEMS` array ends with the `settings` entry. Insert a `control` entry **above** `settings` (so System control sits next to its Settings sibling at the bottom):

```javascript
const NAV_ITEMS = [
  { id: "overview", label: "Overview", icon: "⊞" },
  { id: "alerts", label: "Alerts", icon: "◎" },
  { id: "alert-detail", label: "Alert Detail", icon: "◈" },
  { id: "positions", label: "Positions", icon: "▦" },
  { id: "performance", label: "Performance", icon: "∿" },
  { id: "providers", label: "Providers", icon: "⬡" },
  { id: "replay", label: "Replay", icon: "↺" },
  { id: "source-trace", label: "Source Trace", icon: "⌖" },
  { id: "control", label: "Control", icon: "⏻" },
  { id: "settings", label: "Settings", icon: "⚙" },
];
```

- [ ] **Step 15.2: Commit**

```bash
git add web/signalstack/Sidebar.jsx
git commit -m "feat(dashboard): add Control entry to sidebar navigation"
```

---

## Task 16: Build Settings.jsx

**Files:**
- Create: `web/signalstack/Settings.jsx`

**Conventions to follow** (verified by reading [`Shared.jsx`](../../../web/signalstack/Shared.jsx) and existing components):
- Components are global functions, registered via `Object.assign(window, { ComponentName });` at the bottom of the file (no ES module exports — Babel-standalone runs in script context).
- `Card({ children, style })` is provided by `Shared.jsx` and is the standard container.
- Available palette: `#16A34A` green, `#DC2626` red, `#D97706` amber, `#FAF7F1` cream bg, `#E5E2D8` borders, `#1F1F1F` ink, `#687388` muted text.
- The existing `StatusDot({ status })` from Shared.jsx uses `status` prop with values `"healthy"`, `"degraded"`, `"error"`, `"inactive"`.

- [ ] **Step 16.1: Implement Settings.jsx**

Create `web/signalstack/Settings.jsx`:

```jsx
// Settings tab — sensitivity selector for the desktop app.
// Hides itself with a friendly message when opened in a regular browser
// (no pywebview bridge available).

function Settings() {
  const inDesktopApp = typeof window !== "undefined" && !!window.pywebview;
  const [mode, setMode] = React.useState("medium");
  const [loading, setLoading] = React.useState(inDesktopApp);
  const [toast, setToast] = React.useState(null);

  React.useEffect(() => {
    if (!inDesktopApp) return;
    let cancelled = false;
    window.pywebview.api.get_sensitivity().then((m) => {
      if (cancelled) return;
      setMode(m);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [inDesktopApp]);

  async function pick(newMode) {
    if (!inDesktopApp || newMode === mode) return;
    const prev = mode;
    setMode(newMode);
    const result = await window.pywebview.api.set_sensitivity(newMode);
    if (!result.ok) {
      setMode(prev);
      setToast({ kind: "error", message: result.error || "Failed to save" });
    } else {
      setToast({ kind: "success", message: `Sensitivity set to ${newMode}` });
    }
    setTimeout(() => setToast(null), 2500);
  }

  if (!inDesktopApp) {
    return (
      <div style={{ padding: 16 }}>
        <Card>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Settings</div>
          <div style={{ color: "#687388", fontSize: 12 }}>
            Settings are only available inside the SignalStack desktop app.
          </div>
        </Card>
      </div>
    );
  }

  if (loading) {
    return (
      <div style={{ padding: 16 }}>
        <Card><div style={{ color: "#687388" }}>Loading…</div></Card>
      </div>
    );
  }

  const options = [
    { id: "high",   label: "High",   desc: "A-grade alerts only (most selective)" },
    { id: "medium", label: "Medium", desc: "A and B grade alerts (default)" },
    { id: "low",    label: "Low",    desc: "A, B, and C grade alerts (most permissive)" },
  ];

  return (
    <div style={{ padding: 16 }}>
      <Card>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#1F1F1F", marginBottom: 12 }}>
          Sensitivity
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {options.map((opt) => (
            <label
              key={opt.id}
              style={{
                display: "flex", alignItems: "flex-start", gap: 10,
                padding: 10, border: "1px solid #E5E2D8", borderRadius: 6,
                cursor: "pointer",
                background: mode === opt.id ? "#F0F7FF" : "transparent",
              }}
            >
              <input
                type="radio"
                name="sensitivity"
                checked={mode === opt.id}
                onChange={() => pick(opt.id)}
                style={{ marginTop: 3 }}
              />
              <div>
                <div style={{ fontSize: 12.5, fontWeight: 600, color: "#1F1F1F" }}>{opt.label}</div>
                <div style={{ color: "#687388", fontSize: 11 }}>{opt.desc}</div>
              </div>
            </label>
          ))}
        </div>
        <div style={{ marginTop: 14, color: "#687388", fontSize: 11 }}>
          Changes apply immediately — no restart needed.
        </div>
      </Card>

      {toast && (
        <div
          style={{
            position: "fixed", bottom: 20, right: 20, padding: "10px 14px",
            background: "#fff",
            border: "1px solid",
            borderColor: toast.kind === "error" ? "#DC2626" : "#16A34A",
            borderRadius: 6, fontSize: 12, color: "#1F1F1F",
            boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
          }}
        >
          {toast.message}
        </div>
      )}
    </div>
  );
}

Object.assign(window, { Settings });
```

- [ ] **Step 16.2: Commit**

```bash
git add web/signalstack/Settings.jsx
git commit -m "feat(dashboard): Settings tab with sensitivity radio buttons"
```

---

## Task 17: Build Control.jsx

**Files:**
- Create: `web/signalstack/Control.jsx`

**Important naming note:** `Shared.jsx` already exports a `StatusDot` (with `status` prop and `healthy/degraded/error/inactive` values). To avoid clobbering it, the local component below is named `SystemStatusDot`. Colors match the existing palette (`#16A34A` / `#DC2626` / `#D97706`).

- [ ] **Step 17.1: Implement Control.jsx**

Create `web/signalstack/Control.jsx`:

```jsx
// Control tab — Start/Stop the SignalStack system, with live status + log tail.
// Hides itself with a friendly message when not in the desktop app.

function SystemStatusDot({ state }) {
  const colors = {
    running: "#16A34A",
    stopped: "#DC2626",
    transitioning: "#D97706",
  };
  return (
    <span
      style={{
        display: "inline-block", width: 8, height: 8, borderRadius: "50%",
        background: colors[state] || colors.stopped, marginRight: 10,
        flexShrink: 0,
      }}
    />
  );
}

function Control() {
  const inDesktopApp = typeof window !== "undefined" && !!window.pywebview;

  const [status, setStatus] = React.useState({
    docker: "stopped", postgres: "stopped", workers: "stopped", api: "stopped",
  });
  const [logs, setLogs] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [lastStarted, setLastStarted] = React.useState(null);
  const [sensitivity, setSensitivity] = React.useState("medium");

  React.useEffect(() => {
    if (!inDesktopApp) return;
    let cancelled = false;
    async function poll() {
      try {
        const [s, l, ts, m] = await Promise.all([
          window.pywebview.api.get_status(),
          window.pywebview.api.get_recent_logs(50),
          window.pywebview.api.get_last_started_at(),
          window.pywebview.api.get_sensitivity(),
        ]);
        if (cancelled) return;
        setStatus(s); setLogs(l); setLastStarted(ts); setSensitivity(m);
      } catch (e) {
        // pywebview API can throw during teardown; ignore and keep polling
      }
    }
    poll();
    const id = setInterval(poll, 2000);
    return () => { cancelled = true; clearInterval(id); };
  }, [inDesktopApp]);

  if (!inDesktopApp) {
    return (
      <div style={{ padding: 16 }}>
        <Card>
          <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 8 }}>Control</div>
          <div style={{ color: "#687388", fontSize: 12 }}>
            System control is only available inside the SignalStack desktop app.
          </div>
        </Card>
      </div>
    );
  }

  const allRunning =
    status.docker === "running" && status.postgres === "running" &&
    status.workers === "running" && status.api === "running";
  const fullyStopped = status.workers === "stopped" && status.api === "stopped";

  async function start() {
    setBusy(true); setError(null);
    const result = await window.pywebview.api.start_system();
    if (!result.ok) setError(result.error || "Failed to start");
    setBusy(false);
  }

  async function stop() {
    setBusy(true); setError(null);
    await window.pywebview.api.stop_system();
    setBusy(false);
  }

  const rows = [
    { name: "Docker",   state: status.docker },
    { name: "Postgres", state: status.postgres },
    { name: "Workers",  state: status.workers },
    { name: "API",      state: status.api },
  ];

  return (
    <div style={{ padding: 16, display: "flex", flexDirection: "column", gap: 12 }}>
      <Card>
        <div style={{ fontSize: 13, fontWeight: 700, color: "#1F1F1F", marginBottom: 12 }}>
          System Status
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "auto auto 1fr", rowGap: 6, columnGap: 12, alignItems: "center" }}>
          {rows.map((r) => (
            <React.Fragment key={r.name}>
              <SystemStatusDot state={r.state} />
              <div style={{ fontSize: 12.5, color: "#1F1F1F", fontWeight: 500 }}>{r.name}</div>
              <div style={{ fontSize: 12, color: "#687388", textTransform: "capitalize" }}>{r.state}</div>
            </React.Fragment>
          ))}
        </div>

        <div style={{ marginTop: 20, textAlign: "center" }}>
          {allRunning ? (
            <button
              disabled={busy}
              onClick={stop}
              style={{
                padding: "10px 28px", fontSize: 13, fontWeight: 600,
                background: "#DC2626", color: "#fff", border: "none",
                borderRadius: 6, cursor: busy ? "wait" : "pointer",
                fontFamily: "inherit",
              }}
            >
              {busy ? "Stopping…" : "■ Stop System"}
            </button>
          ) : (
            <button
              disabled={busy || !fullyStopped}
              onClick={start}
              style={{
                padding: "10px 28px", fontSize: 13, fontWeight: 600,
                background: "#16A34A", color: "#fff", border: "none",
                borderRadius: 6, cursor: (busy || !fullyStopped) ? "wait" : "pointer",
                opacity: (busy || !fullyStopped) ? 0.6 : 1,
                fontFamily: "inherit",
              }}
            >
              {busy ? "Starting…" : "▶ Start System"}
            </button>
          )}
        </div>

        {error && (
          <div style={{
            marginTop: 14, padding: 10, fontSize: 12,
            background: "#fff", color: "#DC2626",
            border: "1px solid #DC2626", borderRadius: 6,
          }}>
            {error}
          </div>
        )}

        <div style={{ marginTop: 18, color: "#687388", fontSize: 11, display: "flex", flexDirection: "column", gap: 2 }}>
          <div>Last started: {lastStarted || "—"}</div>
          <div>Sensitivity: <span style={{ textTransform: "capitalize" }}>{sensitivity}</span></div>
        </div>
      </Card>

      <Card>
        <div style={{ fontSize: 12, fontWeight: 700, color: "#1F1F1F", marginBottom: 8 }}>
          Recent log output
        </div>
        <pre style={{
          fontFamily: '"IBM Plex Mono", ui-monospace, monospace', fontSize: 11,
          maxHeight: 220, overflowY: "auto", margin: 0, whiteSpace: "pre-wrap",
          color: "#1F1F1F", lineHeight: 1.5,
        }}>
          {logs.length === 0 ? "(no output yet)" : logs.join("\n")}
        </pre>
      </Card>
    </div>
  );
}

Object.assign(window, { Control });
```

- [ ] **Step 17.2: Commit**

```bash
git add web/signalstack/Control.jsx
git commit -m "feat(dashboard): Control tab with status, Start/Stop, and log tail"
```

---

## Task 18: Wire Control + Settings into SignalStack.html

**Files:**
- Modify: `web/SignalStack.html`

**Note:** The renderScreen switch at [`web/SignalStack.html:108-121`](../../../web/SignalStack.html#L108-L121) already routes `case "settings": return <Settings />;` — so once `Settings.jsx` exists (created in Task 16), the Settings tab will work without further switch changes. We need to add: (a) two new `<script>` includes, and (b) a `case "control":` line.

- [ ] **Step 18.1: Add the new script includes**

In `web/SignalStack.html`, find the existing component-include block (around lines 53-62) which lists each `signalstack/*.jsx` via `<script type="text/babel" src="...">`. Add the two new files immediately after the existing `Alerts.jsx` line, so the block becomes:

```html
<script src="signalstack/api.js"></script>
<script type="text/babel" src="signalstack/Shared.jsx"></script>
<script type="text/babel" src="signalstack/Sidebar.jsx"></script>
<script type="text/babel" src="signalstack/Header.jsx"></script>
<script type="text/babel" src="signalstack/Overview.jsx"></script>
<script type="text/babel" src="signalstack/AlertDetail.jsx"></script>
<script type="text/babel" src="signalstack/Replay.jsx"></script>
<script type="text/babel" src="signalstack/Providers.jsx"></script>
<script type="text/babel" src="signalstack/Performance.jsx"></script>
<script type="text/babel" src="signalstack/Alerts.jsx"></script>
<script type="text/babel" src="signalstack/Control.jsx"></script>
<script type="text/babel" src="signalstack/Settings.jsx"></script>
```

- [ ] **Step 18.2: Add the `case "control":` line to renderScreen**

Find the `renderScreen` function (around line 108). It looks like:

```jsx
const renderScreen = () => {
  switch (screen) {
    case "overview":     return <Overview onNav={handleNav} onSelectAlert={handleSelectAlert} />;
    case "alerts":       return <Alerts onNav={handleNav} onSelectAlert={handleSelectAlert} />;
    case "alert-detail": return <AlertDetail alert={selectedAlert} />;
    case "positions":    return <Performance />;
    case "performance":  return <Performance />;
    case "providers":    return <Providers />;
    case "replay":       return <Replay />;
    case "source-trace": return <SourceTrace />;
    case "settings":     return <Settings />;
    default:             return <Overview onNav={handleNav} onSelectAlert={handleSelectAlert} />;
  }
};
```

Add a `case "control":` line above the existing `case "settings":` line:

```jsx
    case "control":      return <Control />;
    case "settings":     return <Settings />;
```

- [ ] **Step 18.3: Manual visual check (no functionality test yet — that's Task 19)**

Run: `uv run python -m app.desktop`

Expected: Window opens. Sidebar shows "Control" between "Source Trace" and "Settings". Click "Control" → status panel renders with all dots red and "▶ Start System" button visible. Click "Settings" → three radio buttons, "Medium" selected. No JS errors in the webview's devtools console (right-click → Inspect Element on macOS PyWebView).

If `Card` is undefined in the new components, verify that `Shared.jsx` is loaded **before** `Control.jsx` and `Settings.jsx` in the include order above. The existing files use `Object.assign(window, { Card, ... });` to expose primitives, so order matters.

- [ ] **Step 18.4: Commit**

```bash
git add web/SignalStack.html
git commit -m "feat(dashboard): load Control/Settings scripts and wire control route"
```

---

## Task 19: Manual smoke test

**Files:** none modified. This is a verification gate before declaring the feature done.

Follow the spec's [§10 testing strategy](../specs/2026-04-24-signalstack-desktop-app-design.md#10-testing-strategy) manual smoke test entry.

- [ ] **Step 19.1: Quit Docker Desktop manually**

So we can verify auto-launch. From the macOS menu bar Docker icon → "Quit Docker Desktop".

- [ ] **Step 19.2: Launch the app**

Run: `uv run python -m app.desktop`

Expected: Window opens. Sidebar has 7 entries.

- [ ] **Step 19.3: Click Control → click Start**

Expected behavior:
- Docker dot turns yellow ("Starting…")
- Within 30-60 seconds: Docker green
- Then Postgres yellow → green within ~5 seconds
- Then Workers and API green within ~3 seconds
- Last 50 lines of worker/API output appear in log tail

- [ ] **Step 19.4: Click Alerts**

Expected: alerts list loads (or shows empty state if no alerts yet). No "API offline" or CORS errors.

- [ ] **Step 19.5: Click Settings → switch from Medium to High**

Expected: green toast "Sensitivity set to high". Within ~10 seconds, the worker's next loop reads it (you can verify by tailing logs in the Control tab — look for any sensitivity-related log lines, or check `~/.signalstack/desktop_state.json` content).

- [ ] **Step 19.6: Click Stop**

Expected: Workers + API dots flip red within 10 seconds. Postgres stays green.

- [ ] **Step 19.7: Close the window with the X button**

Expected: process exits. Verify no orphans:

```bash
pgrep -f "uvicorn app.main:app"   # should print nothing
pgrep -f "python -m app.main_workers"  # should print nothing
```

If any return PIDs, there's a shutdown bug — investigate before declaring done.

- [ ] **Step 19.8: Try launching twice**

Open two terminals. Run `uv run python -m app.desktop` in both within a few seconds of each other.

Expected: first opens normally; second prints "SignalStack: SignalStack is already running (PID nnnn)." and exits with code 1.

Quit the first instance afterwards.

- [ ] **Step 19.9: Run the full test suite one last time**

Run: `uv run pytest -xvs`

Expected: all tests pass.

Run: `uv run ruff check .`

Expected: no errors.

- [ ] **Step 19.10: Final commit if any cleanups were made**

If steps 19.1-19.9 surfaced any small bugs or polish issues, fix them, run tests, and commit. Otherwise, no commit needed.

---

## Done

After Task 19 passes, the feature is complete:

- Desktop app launches with one command, no terminal juggling
- Auto-launches Docker Desktop on cold start
- Embeds the existing dashboard verbatim (all 5 original tabs work the same)
- Adds Control tab for Start/Stop with live status and log tail
- Adds Settings tab with High/Medium/Low sensitivity selector
- Sensitivity changes take effect within seconds, no restart
- Telegram messages and dashboard alerts always show the candidate's true grade
- All new code unit-tested; sensitivity gate also has an integration test
- Single-instance lock prevents resource collisions
- Window-close cleans up subprocesses

Future work (out of scope, listed in the spec): bundling to a clickable `.app` via `briefcase`, multiple sensitivity profiles, scheduled mode changes.
