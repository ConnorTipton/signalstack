# Operational Robustness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent silent failures by (a) auto-restarting crashed desktop subprocesses and (b) sending a Telegram notification when any provider accumulates N consecutive health-check failures.

**Architecture:** A supervisor thread in `SystemController` polls subprocess status every 5 seconds and restarts any that stopped while `_running` is True. A shared utility function `maybe_alert_degradation()` is wired into the three health-recording workers (LabelWorker, TradierWorker, AlpacaBarWorker); it fires exactly once when `consecutive_failures` reaches the configured threshold, then is silent until the count resets and crosses again.

**Tech Stack:** Python stdlib `threading`, existing `TelegramClient`, existing `SubprocessController`.

---

## File Map

- **Create:** `app/providers/health_monitor.py` — single function `maybe_alert_degradation()`
- **Modify:** `app/desktop/system.py` — add supervisor thread and restart cooldown
- **Modify:** `app/ingest_news/label_worker.py` — accept optional `telegram_client`; call `maybe_alert_degradation`
- **Modify:** `app/ingest_market/tradier_worker.py` — same pattern
- **Modify:** `app/ingest_market/alpaca_bar_worker.py` — same pattern
- **Modify:** `app/main_workers.py` — pass `telegram` to the three workers
- **Test:** `tests/unit/test_health_monitor.py` — new
- **Test:** `tests/unit/test_system.py` — extend existing

---

## Task 1: `health_monitor.py` — degradation alert utility

**Files:**
- Create: `app/providers/health_monitor.py`
- Create: `tests/unit/test_health_monitor.py`

- [ ] **Step 1.1: Write the failing test**

```python
# tests/unit/test_health_monitor.py
"""Unit tests for the provider degradation alert utility."""

from unittest.mock import MagicMock

from app.providers.health_monitor import maybe_alert_degradation


def _mock_telegram() -> MagicMock:
    t = MagicMock()
    t.send_message = MagicMock()
    return t


def test_no_alert_below_threshold():
    t = _mock_telegram()
    maybe_alert_degradation("tradier", consecutive_failures=2, threshold=3, telegram_client=t)
    t.send_message.assert_not_called()


def test_alert_fires_exactly_at_threshold():
    t = _mock_telegram()
    maybe_alert_degradation("tradier", consecutive_failures=3, threshold=3, telegram_client=t)
    t.send_message.assert_called_once()
    msg = t.send_message.call_args[0][0]
    assert "tradier" in msg
    assert "3" in msg


def test_no_alert_above_threshold():
    t = _mock_telegram()
    maybe_alert_degradation("tradier", consecutive_failures=4, threshold=3, telegram_client=t)
    t.send_message.assert_not_called()


def test_no_alert_when_telegram_is_none():
    # Must not raise even without a client
    maybe_alert_degradation("tradier", consecutive_failures=3, threshold=3, telegram_client=None)


def test_no_alert_when_healthy():
    t = _mock_telegram()
    maybe_alert_degradation("tradier", consecutive_failures=0, threshold=3, telegram_client=t)
    t.send_message.assert_not_called()
```

- [ ] **Step 1.2: Run to confirm FAIL**

```bash
uv run pytest tests/unit/test_health_monitor.py -v
```

Expected: `ImportError` — `health_monitor` does not exist yet.

- [ ] **Step 1.3: Implement `health_monitor.py`**

```python
# app/providers/health_monitor.py
"""Shared utility for provider degradation Telegram alerts."""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_DEFAULT_THRESHOLD = 3


def maybe_alert_degradation(
    provider_name: str,
    consecutive_failures: int,
    threshold: int,
    telegram_client: object | None,
) -> None:
    """Send a Telegram alert exactly when consecutive_failures reaches threshold.

    Fires once at the threshold, then is silent until failures reset and cross
    again. Pass threshold=0 to disable.
    """
    if telegram_client is None or threshold <= 0:
        return
    if consecutive_failures != threshold:
        return
    msg = (
        f"WARNING: provider '{provider_name}' has failed {threshold} consecutive "
        f"health checks. Check logs — signals from this provider may be degraded."
    )
    try:
        telegram_client.send_message(msg)
        log.warning("Sent degradation alert for %s (%d failures)", provider_name, threshold)
    except Exception as exc:
        log.warning("Failed to send degradation alert for %s: %s", provider_name, exc)
```

- [ ] **Step 1.4: Run tests**

```bash
uv run pytest tests/unit/test_health_monitor.py -v
```

Expected: all 5 tests PASS.

- [ ] **Step 1.5: Commit**

```bash
git add app/providers/health_monitor.py tests/unit/test_health_monitor.py
git commit -m "feat(providers): add maybe_alert_degradation utility for threshold alerting"
```

---

## Task 2: Wire degradation alerts into LabelWorker

**Files:**
- Modify: `app/ingest_news/label_worker.py`
- Modify: `tests/unit/test_label_worker.py`

- [ ] **Step 2.1: Write the failing test**

Add to `tests/unit/test_label_worker.py`:

```python
def test_label_worker_sends_degradation_alert_at_threshold():
    """Telegram client should receive exactly one message when failures hit threshold."""
    from app.ingest_news.label_worker import LabelWorker

    telegram = MagicMock()
    telegram.send_message = MagicMock()

    worker = LabelWorker(
        client=_mock_client(),
        interval_seconds=9999,
        telegram_client=telegram,
        degradation_threshold=2,
    )
    # Simulate 2 consecutive failures recorded
    worker._consecutive_failures = 2
    worker._record_health(is_healthy=False)

    telegram.send_message.assert_called_once()
```

(Add `from unittest.mock import MagicMock` to the imports if not already present.)

- [ ] **Step 2.2: Run to confirm FAIL**

```bash
uv run pytest tests/unit/test_label_worker.py::test_label_worker_sends_degradation_alert_at_threshold -v
```

Expected: `TypeError` — `LabelWorker.__init__` does not accept `telegram_client`.

- [ ] **Step 2.3: Update `LabelWorker`**

In `app/ingest_news/label_worker.py`, add the import at the top:

```python
from app.providers.health_monitor import maybe_alert_degradation
```

Update `__init__` signature (add two new optional parameters after `batch_size`):

```python
def __init__(
    self,
    client: AnthropicClient | None = None,
    *,
    interval_seconds: float = _DEFAULT_INTERVAL,
    batch_size: int = _DEFAULT_BATCH,
    telegram_client: object | None = None,
    degradation_threshold: int = 3,
) -> None:
    # ... existing body unchanged ...
    self._telegram = telegram_client
    self._degradation_threshold = degradation_threshold
```

Update `_record_health` to call the utility after writing to DB:

```python
def _record_health(self, *, is_healthy: bool, error: str | None = None) -> None:
    confidence = 1.0 if is_healthy else max(0.0, 1.0 - 0.2 * self._consecutive_failures)
    with SessionLocal() as db:
        db.add(
            ProviderHealth(
                checked_at=datetime.now(UTC),
                provider_name="anthropic",
                is_healthy=is_healthy,
                provider_confidence=round(confidence, 3),
                last_success_at=self._last_success_at,
                consecutive_failures=self._consecutive_failures,
                error_message=error,
            )
        )
        db.commit()
    maybe_alert_degradation(
        "anthropic",
        consecutive_failures=self._consecutive_failures,
        threshold=self._degradation_threshold,
        telegram_client=self._telegram,
    )
```

- [ ] **Step 2.4: Run tests**

```bash
uv run pytest tests/unit/test_label_worker.py -v
```

Expected: all PASS.

- [ ] **Step 2.5: Commit**

```bash
git add app/ingest_news/label_worker.py tests/unit/test_label_worker.py
git commit -m "feat(label_worker): send Telegram degradation alert after N consecutive failures"
```

---

## Task 3: Wire degradation alerts into TradierWorker and AlpacaBarWorker

**Files:**
- Modify: `app/ingest_market/tradier_worker.py`
- Modify: `app/ingest_market/alpaca_bar_worker.py`

No new test files — the pattern is identical to Task 2 and is already validated by `test_health_monitor.py`. Add one test per worker to the existing test files if they have unit test coverage; otherwise skip (integration tests cover these paths).

- [ ] **Step 3.1: Update `TradierWorker`**

Open `app/ingest_market/tradier_worker.py`. Add import:

```python
from app.providers.health_monitor import maybe_alert_degradation
```

Add `telegram_client` and `degradation_threshold` to `__init__`:

```python
def __init__(
    self,
    # ... existing params ...
    telegram_client: object | None = None,
    degradation_threshold: int = 3,
) -> None:
    # ... existing body ...
    self._telegram = telegram_client
    self._degradation_threshold = degradation_threshold
```

At the end of `_record_health_sync` (after `db.commit()`), add:

```python
maybe_alert_degradation(
    "tradier",
    consecutive_failures=failures,
    threshold=self._degradation_threshold,
    telegram_client=self._telegram,
)
```

- [ ] **Step 3.2: Update `AlpacaBarWorker`**

Same pattern in `app/ingest_market/alpaca_bar_worker.py`:

Add import:
```python
from app.providers.health_monitor import maybe_alert_degradation
```

Add to `__init__`:
```python
    telegram_client: object | None = None,
    degradation_threshold: int = 3,
```

```python
    self._telegram = telegram_client
    self._degradation_threshold = degradation_threshold
```

At the end of `_record_health_sync` (after `db.commit()`):
```python
maybe_alert_degradation(
    "alpaca",
    consecutive_failures=self._consecutive_failures,
    threshold=self._degradation_threshold,
    telegram_client=self._telegram,
)
```

- [ ] **Step 3.3: Run all tests**

```bash
uv run pytest -q
```

Expected: all PASS (the workers' new params have defaults so existing tests still work).

- [ ] **Step 3.4: Commit**

```bash
git add app/ingest_market/tradier_worker.py app/ingest_market/alpaca_bar_worker.py
git commit -m "feat(market_workers): wire degradation alerts into Tradier and Alpaca workers"
```

---

## Task 4: Pass telegram client to workers in `main_workers.py`

**Files:**
- Modify: `app/main_workers.py`

- [ ] **Step 4.1: Update LabelWorker construction**

In `app/main_workers.py`, find the `LabelWorker` instantiation:

```python
add_task(lambda: LabelWorker().run(), "label")
```

Change to:

```python
add_task(lambda: LabelWorker(telegram_client=telegram).run(), "label")
```

- [ ] **Step 4.2: Update TradierWorker construction**

Find:
```python
add_task(lambda: TradierWorker(symbols=tickers).run(), "tradier_quotes")
```

Change to:
```python
add_task(lambda: TradierWorker(symbols=tickers, telegram_client=telegram).run(), "tradier_quotes")
```

- [ ] **Step 4.3: Update AlpacaBarWorker construction**

Find:
```python
add_task(
    lambda: AlpacaBarWorker(symbols=tickers, client=alpaca_market).run(), "alpaca_bars"
)
```

Change to:
```python
add_task(
    lambda: AlpacaBarWorker(symbols=tickers, client=alpaca_market, telegram_client=telegram).run(),
    "alpaca_bars",
)
```

- [ ] **Step 4.4: Run tests and lint**

```bash
uv run pytest -q && uv run ruff check .
```

Expected: all PASS, no lint errors.

- [ ] **Step 4.5: Commit**

```bash
git add app/main_workers.py
git commit -m "feat(workers): pass Telegram client to workers for degradation alerts"
```

---

## Task 5: Desktop subprocess supervisor

**Files:**
- Modify: `app/desktop/system.py`
- Modify: `tests/unit/test_system.py`

- [ ] **Step 5.1: Write the failing tests**

Add to `tests/unit/test_system.py`:

```python
import time


def test_supervisor_restarts_crashed_worker(buf: LogBuffer) -> None:
    """If a subprocess exits after start(), the supervisor restarts it."""
    ctrl = _make_controller(buf)
    restart_calls: list[str] = []

    def fake_workers_status_side_effect() -> str:
        # First call returns running, subsequent calls return stopped (simulating crash)
        if not restart_calls:
            return "running"
        return "stopped"

    with (
        patch("app.desktop.system.docker_running", return_value=True),
        patch("app.desktop.system.postgres_running", return_value=True),
        patch.object(ctrl._workers, "start") as ws,
        patch.object(ctrl._api, "start"),
        patch.object(ctrl._workers, "status", side_effect=fake_workers_status_side_effect),
        patch.object(ctrl._api, "status", return_value="running"),
    ):
        ctrl.start()
        # Record that original start was called
        restart_calls.append("original")
        # Give supervisor thread time to detect the "crash" and restart
        time.sleep(0.2)
        ctrl.stop()

    # start() called more than once (original + at least one restart)
    assert ws.call_count >= 2


def test_supervisor_does_not_restart_after_stop(buf: LogBuffer) -> None:
    """After stop() is called, the supervisor must not trigger further restarts."""
    ctrl = _make_controller(buf)
    with (
        patch("app.desktop.system.docker_running", return_value=True),
        patch("app.desktop.system.postgres_running", return_value=True),
        patch.object(ctrl._workers, "start") as ws,
        patch.object(ctrl._api, "start"),
        patch.object(ctrl._workers, "status", return_value="stopped"),
        patch.object(ctrl._api, "status", return_value="stopped"),
        patch.object(ctrl._workers, "stop"),
        patch.object(ctrl._api, "stop"),
    ):
        ctrl.start()
        ctrl.stop()
        time.sleep(0.15)

    # Only one start call — the initial one; none after stop
    assert ws.call_count == 1
```

- [ ] **Step 5.2: Run to confirm FAIL**

```bash
uv run pytest tests/unit/test_system.py::test_supervisor_restarts_crashed_worker tests/unit/test_system.py::test_supervisor_does_not_restart_after_stop -v
```

Expected: FAIL — supervisor thread does not exist yet.

- [ ] **Step 5.3: Implement supervisor in `system.py`**

Add to the top of `app/desktop/system.py`:

```python
import threading
import time
```

Add module-level constants after the existing imports:

```python
_SUPERVISOR_POLL_S = 5.0
_RESTART_COOLDOWN_S = 30.0
```

Update `SystemController.__init__` to add new fields:

```python
def __init__(self, *, repo_root: Path, log_buffer: LogBuffer) -> None:
    self._repo_root = repo_root
    self._log = log_buffer
    self._last_started_at: datetime | None = None
    self._we_launched_docker: bool = False
    self._running: bool = False
    self._supervisor_thread: threading.Thread | None = None
    self._last_restart: dict[str, float] = {}  # name -> monotonic timestamp

    self._api = SubprocessController(...)   # unchanged
    self._workers = SubprocessController(...)  # unchanged
```

Add `_supervise()` and `_start_supervisor()` / `_stop_supervisor()` methods:

```python
def _supervise(self) -> None:
    while self._running:
        time.sleep(_SUPERVISOR_POLL_S)
        if not self._running:
            break
        now = time.monotonic()
        for name, ctrl in (("workers", self._workers), ("api", self._api)):
            if ctrl.status() == "stopped":
                last = self._last_restart.get(name, 0.0)
                if now - last >= _RESTART_COOLDOWN_S:
                    self._log.append(f"[supervisor] {name} crashed — restarting")
                    ctrl.start()
                    self._last_restart[name] = now
                else:
                    remaining = int(_RESTART_COOLDOWN_S - (now - last))
                    self._log.append(
                        f"[supervisor] {name} stopped; cooldown {remaining}s remaining"
                    )

def _start_supervisor(self) -> None:
    self._running = True
    self._last_restart.clear()
    self._supervisor_thread = threading.Thread(
        target=self._supervise, daemon=True, name="supervisor"
    )
    self._supervisor_thread.start()

def _stop_supervisor(self) -> None:
    self._running = False
    if self._supervisor_thread is not None:
        self._supervisor_thread.join(timeout=_SUPERVISOR_POLL_S + 1.0)
        self._supervisor_thread = None
```

Update `start()` — add `self._start_supervisor()` at the very end, just before `return StartResult(ok=True, error=None)`:

```python
    self._start_supervisor()
    return StartResult(ok=True, error=None)
```

Update `stop()` — add `self._stop_supervisor()` as the first line:

```python
def stop(self) -> None:
    self._stop_supervisor()
    self._workers.stop(timeout=10.0)
    self._api.stop(timeout=10.0)
    # ... rest unchanged
```

- [ ] **Step 5.4: Run all tests**

```bash
uv run pytest tests/unit/test_system.py -v
```

Expected: all PASS.

- [ ] **Step 5.5: Run full suite and lint**

```bash
uv run pytest -q && uv run ruff check .
```

Expected: all PASS, no errors.

- [ ] **Step 5.6: Commit**

```bash
git add app/desktop/system.py tests/unit/test_system.py
git commit -m "feat(desktop): add supervisor thread that auto-restarts crashed subprocesses"
```

---

## Done

After all tasks complete:
- Telegram message fires once when any of `anthropic`, `tradier`, or `alpaca` hits 3 consecutive failures
- Desktop app automatically restarts crashed workers or API subprocess, with 30s cooldown
- All 652+ tests still pass; ruff clean
- Push and start a fresh session for the next plan
