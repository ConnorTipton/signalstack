# Trace IDs and Article Links Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** (a) Make every Telegram alert include a clickable link to the source news article. (b) Add a `pipeline_run_id` UUID that ties a labeling call to its downstream log lines, so debugging a specific alert is a single grep.

**Architecture:** The article URL is already stored in `NewsArticle.url`. The `AlertWorker` currently fetches only the news summary; it will also fetch the article URL and pass it through to the formatter. The formatter appends a plain-text URL line which Telegram auto-renders as a hyperlink. For trace IDs: a UUID is generated per article in `_label_one()`, stored in `llm_news_labels.pipeline_run_id` (new nullable column), and threaded through log calls. Since `DetectedEvent.llm_label_id` links back to `LlmNewsLabel`, the full chain is queryable from the trace ID without touching every table.

**Tech Stack:** Python `uuid`, Alembic migration, existing `TelegramClient` (no mode change needed — Telegram auto-links plain URLs).

---

## File Map

- **Modify:** `app/alerts/worker.py` — `_fetch_news_summary` → `_fetch_news_context` returns `(summary, url)`
- **Modify:** `app/alerts/formatter.py` — `build()` + `render()` accept and render `news_url`
- **Modify:** `app/db/models/news.py` — add `pipeline_run_id` UUID column to `LlmNewsLabel`
- **New:** `alembic/versions/0011_llm_pipeline_run_id.py` — migration
- **Modify:** `app/ingest_news/label_worker.py` — generate UUID, log it, store it
- **Test:** `tests/unit/test_alert_formatter.py` — extend for URL rendering
- **Test:** `tests/unit/test_alert_worker.py` — extend for URL fetch
- **Test:** `tests/unit/test_label_worker.py` — extend for pipeline_run_id

---

## Task 1: Article URL in alerts (formatter)

**Files:**
- Modify: `app/alerts/formatter.py`
- Modify: `tests/unit/test_alert_formatter.py`

- [ ] **Step 1.1: Write failing tests**

Add to `tests/unit/test_alert_formatter.py`:

```python
def test_render_includes_article_url_when_present():
    """When news_url is provided, render() must include it in the output."""
    from app.alerts.formatter import AlertFormatter
    from app.db.models.execution import Alert
    from unittest.mock import MagicMock

    formatter = AlertFormatter()
    candidate = MagicMock()
    candidate.id = 1
    candidate.symbol_id = 1
    candidate.ticker = "AAPL"
    candidate.grade = "A"
    candidate.status = "promoted"
    candidate.rejection_reason = None
    candidate.contract_type = "call"
    candidate.contract_symbol = "AAPL260117C00200000"
    candidate.contract_expiration = None
    candidate.contract_strike = 200.0
    candidate.contract_spread_pct = 0.08
    candidate.contract_oi = 1500
    candidate.contract_volume = 400
    candidate.score = 82.0
    candidate.price_score = 20.0
    candidate.options_score = 18.0

    alert = formatter.build(
        candidate,
        news_summary="Apple beats earnings.",
        news_url="https://example.com/article/123",
        dry_run=False,
    )
    rendered = AlertFormatter.render(alert)

    assert "https://example.com/article/123" in rendered


def test_render_omits_source_line_when_no_url():
    from app.alerts.formatter import AlertFormatter
    from unittest.mock import MagicMock

    formatter = AlertFormatter()
    candidate = MagicMock()
    candidate.id = 1
    candidate.symbol_id = 1
    candidate.ticker = "MSFT"
    candidate.grade = "B"
    candidate.status = "promoted"
    candidate.rejection_reason = None
    candidate.contract_type = "call"
    candidate.contract_symbol = "MSFT260117C00400000"
    candidate.contract_expiration = None
    candidate.contract_strike = 400.0
    candidate.contract_spread_pct = 0.09
    candidate.contract_oi = 800
    candidate.contract_volume = 200
    candidate.score = 72.0
    candidate.price_score = 18.0
    candidate.options_score = 15.0

    alert = formatter.build(
        candidate,
        news_summary="Microsoft beats earnings.",
        news_url=None,
        dry_run=False,
    )
    rendered = AlertFormatter.render(alert)
    assert "Source:" not in rendered
```

- [ ] **Step 1.2: Run to confirm FAIL**

```bash
uv run pytest tests/unit/test_alert_formatter.py::test_render_includes_article_url_when_present tests/unit/test_alert_formatter.py::test_render_omits_source_line_when_no_url -v
```

Expected: FAIL — `build()` does not accept `news_url`.

- [ ] **Step 1.3: Add `news_article_url` column to `Alert` model**

Open `app/db/models/execution.py`. Add after `data_note`:

```python
    news_article_url: Mapped[str | None] = mapped_column(Text, nullable=True)
```

This column stores the source article URL on the alert for permanent reference without needing to re-join.

- [ ] **Step 1.4: Update `AlertFormatter`**

In `app/alerts/formatter.py`:

Update `build()` signature — add `news_url: str | None = None` parameter:

```python
def build(
    self,
    candidate: SignalCandidate,
    *,
    news_summary: str | None = None,
    news_url: str | None = None,
    dry_run: bool = True,
) -> Alert:
```

Inside `build()`, set the new field:

```python
    return Alert(
        # ... existing fields unchanged ...
        news_article_url=news_url,
    )
```

Update `render()` — append source line when URL is present:

```python
@staticmethod
def render(alert: Alert) -> str:
    score_str = f"{float(alert.score):.0f}" if alert.score is not None else "?"
    lines = [
        f"{alert.ticker.upper()} {(alert.direction or '').upper()} | Score {score_str} | Grade {alert.grade or '?'}",
        f"Reason: {alert.reason or '—'}",
        f"Contract: {_render_contract(alert)}",
        f"Entry: {alert.entry_condition or '—'}",
        f"Invalidation: {alert.invalidation or '—'}",
        f"Target 1: {alert.target1 or '—'}",
        f"Target 2: {alert.target2 or '—'}",
        f"Time stop: {alert.time_stop or '—'}",
        f"Liquidity: {alert.liquidity_note or '—'}",
        f"Data note: {alert.data_note or '—'}",
    ]
    if alert.news_article_url:
        lines.append(f"Source: {alert.news_article_url}")
    if alert.dry_run:
        lines.insert(0, "[DRY RUN]")
    return "\n".join(lines)
```

- [ ] **Step 1.5: Generate migration for `news_article_url` on `alerts`**

```bash
uv run alembic revision --autogenerate -m "add news_article_url to alerts"
```

Rename the file:

```bash
mv alembic/versions/*add_news_article_url*.py alembic/versions/0011_news_article_url_on_alerts.py
```

Verify the migration adds `op.add_column('alerts', sa.Column('news_article_url', sa.Text(), nullable=True))`.

Apply it:

```bash
uv run alembic upgrade head
```

- [ ] **Step 1.6: Run tests**

```bash
uv run pytest tests/unit/test_alert_formatter.py -v
```

Expected: all PASS.

- [ ] **Step 1.7: Commit**

```bash
git add app/alerts/formatter.py app/db/models/execution.py alembic/versions/0011_news_article_url_on_alerts.py
git commit -m "feat(alerts): add article URL to Alert model and render it in Telegram message"
```

---

## Task 2: Fetch article URL in `AlertWorker`

**Files:**
- Modify: `app/alerts/worker.py`
- Modify: `tests/unit/test_alert_worker.py`

- [ ] **Step 2.1: Write failing test**

Add to `tests/unit/test_alert_worker.py`:

```python
def test_alert_worker_passes_article_url_to_formatter():
    """When a news article has a URL, it must reach the formatter's build() call."""
    from unittest.mock import MagicMock, patch
    from app.alerts.worker import AlertWorker

    worker = AlertWorker(dry_run=False)

    candidate = MagicMock()
    candidate.id = 99
    candidate.grade = "A"
    candidate.news_event_id = 7

    news_event = MagicMock()
    news_event.one_sentence_summary = "Big earnings beat."
    news_event.news_article_id = 3

    article = MagicMock()
    article.url = "https://example.com/press/123"

    db = MagicMock()
    db.query.return_value.filter.return_value.first.side_effect = [
        news_event,  # first call: DetectedEvent query
        article,     # second call: NewsArticle query
    ]

    captured_url: list = []
    original_build = worker._formatter.build

    def fake_build(cand, *, news_summary=None, news_url=None, dry_run=True):
        captured_url.append(news_url)
        return original_build(cand, news_summary=news_summary, news_url=news_url, dry_run=dry_run)

    worker._formatter.build = fake_build
    worker._fetch_unalerted_candidates = lambda db, batch_size: [candidate]
    worker._fetch_pending_alerts = lambda db, max_retries: []
    worker._send = lambda alert, now: None

    worker.run_once(db)

    assert captured_url == ["https://example.com/press/123"]
```

- [ ] **Step 2.2: Run to confirm FAIL**

```bash
uv run pytest tests/unit/test_alert_worker.py::test_alert_worker_passes_article_url_to_formatter -v
```

Expected: FAIL — worker does not fetch article URL.

- [ ] **Step 2.3: Update `AlertWorker`**

In `app/alerts/worker.py`, add `NewsArticle` import:

```python
from app.db.models.news import NewsArticle
```

Replace `_fetch_news_summary` with `_fetch_news_context`:

```python
@staticmethod
def _fetch_news_context(
    db: Session, news_event_id: int | None
) -> tuple[str | None, str | None]:
    """Return (one_sentence_summary, article_url) for the news detected event."""
    if news_event_id is None:
        return None, None
    event = db.query(DetectedEvent).filter(DetectedEvent.id == news_event_id).first()
    if event is None:
        return None, None
    summary = event.one_sentence_summary
    url: str | None = None
    if event.news_article_id is not None:
        article = db.query(NewsArticle).filter(NewsArticle.id == event.news_article_id).first()
        if article is not None:
            url = article.url
    return summary, url
```

In `run_once()`, replace the call to `_fetch_news_summary`:

```python
            news_summary, news_url = self._fetch_news_context(db, candidate.news_event_id)
            alert = self._formatter.build(
                candidate, news_summary=news_summary, news_url=news_url, dry_run=self._dry_run
            )
```

Remove the old `_fetch_news_summary` static method entirely.

- [ ] **Step 2.4: Run all alert worker tests**

```bash
uv run pytest tests/unit/test_alert_worker.py -v
```

Expected: all PASS. (If any existing test directly calls `_fetch_news_summary`, update those call sites to `_fetch_news_context`.)

- [ ] **Step 2.5: Run full suite**

```bash
uv run pytest -q
```

Expected: all PASS.

- [ ] **Step 2.6: Commit**

```bash
git add app/alerts/worker.py tests/unit/test_alert_worker.py
git commit -m "feat(alert_worker): fetch article URL from NewsArticle and pass to formatter"
```

---

## Task 3: Pipeline trace ID in `LlmNewsLabel`

**Files:**
- Modify: `app/db/models/news.py`
- New: `alembic/versions/0012_llm_pipeline_run_id.py`
- Modify: `app/ingest_news/label_worker.py`
- Modify: `tests/unit/test_label_worker.py`

- [ ] **Step 3.1: Add `pipeline_run_id` to `LlmNewsLabel`**

In `app/db/models/news.py`, add import at top if not present:

```python
from sqlalchemy.dialects.postgresql import UUID as PGUUID
```

Add field to `LlmNewsLabel` after `processing_ms`:

```python
    pipeline_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
```

Using `String(36)` rather than PostgreSQL UUID type keeps SQLite tests working without a dialect switch.

- [ ] **Step 3.2: Generate migration**

```bash
uv run alembic revision --autogenerate -m "add pipeline_run_id to llm_news_labels"
mv alembic/versions/*pipeline_run_id*.py alembic/versions/0012_llm_pipeline_run_id.py
uv run alembic upgrade head
```

Verify migration adds:
```
op.add_column('llm_news_labels', sa.Column('pipeline_run_id', sa.String(length=36), nullable=True))
op.create_index(...)
```

- [ ] **Step 3.3: Write failing test**

Add to `tests/unit/test_label_worker.py`:

```python
async def test_label_worker_stores_pipeline_run_id():
    """Each article labeling call must persist a non-null pipeline_run_id UUID."""
    article = MagicMock()
    article.id = 77
    article.title = "Apple raises guidance significantly above estimates"
    article.body = "Revenue beat by 12%."

    captured: list[dict] = []

    async def fake_persist(*args, **kwargs):
        # Signature: article_id, model_name, prompt_text, response_text,
        #            parsed, processing_ms, input_tokens, output_tokens, pipeline_run_id
        captured.append({"pipeline_run_id": args[8]})

    worker = LabelWorker(client=_mock_client(), interval_seconds=9999)
    worker._persist_label = fake_persist
    worker._fetch_unlabeled = lambda n: [article]

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(captured) == 1
    run_id = captured[0]["pipeline_run_id"]
    assert run_id is not None
    # Must be a valid UUID string (8-4-4-4-12)
    import uuid
    uuid.UUID(run_id)  # raises ValueError if invalid
```

- [ ] **Step 3.4: Run to confirm FAIL**

```bash
uv run pytest tests/unit/test_label_worker.py::test_label_worker_stores_pipeline_run_id -v
```

Expected: FAIL — no `pipeline_run_id` argument in `_persist_label`.

- [ ] **Step 3.5: Update `LabelWorker` to generate and store trace ID**

In `app/ingest_news/label_worker.py`, add import:

```python
import uuid
```

Update `_label_one`:

```python
async def _label_one(self, article: NewsArticle) -> None:
    run_id = str(uuid.uuid4())
    prompt = build_prompt(article.title, article.body)
    result = await self._client.generate(prompt)
    parsed = parse_response(result.text)
    log.info(
        "[run=%s] Labeled article %d: event_type=%s polarity=%s importance=%.2f "
        "tokens(in=%d out=%d)",
        run_id,
        article.id,
        parsed.get("event_type"),
        parsed.get("polarity"),
        parsed.get("importance") or 0.0,
        result.input_tokens,
        result.output_tokens,
    )
    await asyncio.to_thread(
        self._persist_label,
        article.id,
        self._client._model,  # noqa: SLF001
        prompt,
        result.text,
        parsed,
        result.processing_ms,
        result.input_tokens,
        result.output_tokens,
        run_id,
    )
```

Update `_persist_label` signature:

```python
@staticmethod
def _persist_label(
    article_id: int,
    model_name: str,
    prompt_text: str,
    response_text: str,
    parsed: dict,
    processing_ms: int,
    input_tokens: int,
    output_tokens: int,
    pipeline_run_id: str,
) -> None:
    with SessionLocal() as db:
        LabelWorker._write_label(
            db, article_id, model_name, prompt_text, response_text,
            parsed, processing_ms, input_tokens, output_tokens, pipeline_run_id,
        )
        db.commit()
```

Update `_write_label` to pass `pipeline_run_id` to the ORM object:

```python
@staticmethod
def _write_label(
    db: Session,
    article_id: int,
    model_name: str,
    prompt_text: str,
    response_text: str,
    parsed: dict,
    processing_ms: int,
    input_tokens: int,
    output_tokens: int,
    pipeline_run_id: str,
) -> None:
    db.add(
        LlmNewsLabel(
            article_id=article_id,
            model_name=model_name,
            prompt_text=prompt_text,
            response_text=response_text,
            event_type=parsed.get("event_type"),
            polarity=parsed.get("polarity"),
            importance=parsed.get("importance"),
            confidence=parsed.get("confidence"),
            one_sentence_summary=parsed.get("one_sentence_summary"),
            processing_ms=processing_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            pipeline_run_id=pipeline_run_id,
        )
    )
```

- [ ] **Step 3.6: Run all tests**

```bash
uv run pytest tests/unit/test_label_worker.py -v
```

Expected: all PASS.

- [ ] **Step 3.7: Run full suite and lint**

```bash
uv run pytest -q && uv run ruff check .
```

Expected: all PASS, no errors.

- [ ] **Step 3.8: Commit**

```bash
git add app/db/models/news.py alembic/versions/0012_llm_pipeline_run_id.py app/ingest_news/label_worker.py tests/unit/test_label_worker.py
git commit -m "feat(label_worker): generate pipeline_run_id UUID per label call for log tracing"
```

---

## Done

After all tasks complete:
- Every Telegram alert includes a `Source: <url>` line at the bottom when the article has a URL; Telegram renders it as a clickable hyperlink
- Every `llm_news_labels` row carries a `pipeline_run_id` UUID; grep logs for `[run=<uuid>]` to trace any label call end-to-end
- Two Alembic migrations applied cleanly
- All tests pass; ruff clean
- Push and start a fresh session for the next plan
