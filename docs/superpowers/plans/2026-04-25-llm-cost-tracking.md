# LLM Cost Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track Anthropic token usage on every LLM call, store it in the DB, and surface a daily cost estimate (via Telegram and a CLI script) so you can monitor budget against the $100/month cap.

**Architecture:** `AnthropicClient.generate()` is extended to return a `LLMResult` dataclass that includes `input_tokens` and `output_tokens` (from `message.usage` on the SDK response). Two nullable columns are added to `llm_news_labels`. A `scripts/check_llm_spend.py` CLI script queries today's totals and prints estimated cost. The `LabelWorker` fires a daily Telegram summary at the start of the first cycle on a new UTC day.

**Tech Stack:** Anthropic SDK `message.usage`, Alembic migration, Python `dataclasses`.

**Pricing reference (Claude Haiku 4.5):** $0.80 per million input tokens, $4.00 per million output tokens.

---

## File Map

- **Modify:** `app/llm/anthropic_client.py` — `generate()` returns `LLMResult` dataclass
- **Modify:** `app/db/models/news.py` — add `input_tokens`, `output_tokens` to `LlmNewsLabel`
- **New:** `alembic/versions/0010_llm_token_counts.py` — migration
- **Modify:** `app/ingest_news/label_worker.py` — capture token counts; fire daily Telegram summary
- **New:** `scripts/check_llm_spend.py` — CLI script for on-demand cost check
- **Test:** `tests/unit/test_label_worker.py` — update mock to match new return type
- **Test:** `tests/unit/test_llm_spend.py` — new, tests the spend query function

---

## Task 1: `LLMResult` dataclass + updated `generate()`

**Files:**
- Modify: `app/llm/anthropic_client.py`

- [ ] **Step 1.1: Write the failing test**

```python
# tests/unit/test_anthropic_client.py  (create if it doesn't exist)
"""Unit tests for AnthropicClient."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.llm.anthropic_client import AnthropicClient, LLMResult


@pytest.mark.asyncio
async def test_generate_returns_llm_result():
    """generate() must return an LLMResult with text, timing, and token counts."""
    fake_message = MagicMock()
    fake_message.content = [MagicMock(text="hello")]
    fake_message.usage = MagicMock(input_tokens=12, output_tokens=5)

    client = AnthropicClient(api_key="test-key")
    with patch.object(client._client.messages, "create", new=AsyncMock(return_value=fake_message)):
        result = await client.generate("test prompt")

    assert isinstance(result, LLMResult)
    assert result.text == "hello"
    assert result.input_tokens == 12
    assert result.output_tokens == 5
    assert result.processing_ms >= 0


@pytest.mark.asyncio
async def test_generate_handles_empty_content():
    fake_message = MagicMock()
    fake_message.content = []
    fake_message.usage = MagicMock(input_tokens=10, output_tokens=0)

    client = AnthropicClient(api_key="test-key")
    with patch.object(client._client.messages, "create", new=AsyncMock(return_value=fake_message)):
        result = await client.generate("test prompt")

    assert result.text == ""
    assert result.output_tokens == 0
```

- [ ] **Step 1.2: Run to confirm FAIL**

```bash
uv run pytest tests/unit/test_anthropic_client.py -v
```

Expected: `ImportError` — `LLMResult` does not exist.

- [ ] **Step 1.3: Update `anthropic_client.py`**

```python
# app/llm/anthropic_client.py
"""Anthropic Claude client for LLM news labeling."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import anthropic

log = logging.getLogger(__name__)


@dataclass
class LLMResult:
    text: str
    processing_ms: int
    input_tokens: int
    output_tokens: int


class AnthropicClient:
    """Thin wrapper around the Anthropic Messages API."""

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 256,
    ) -> None:
        self._model = model
        self._max_tokens = max_tokens
        self._client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(self, prompt: str) -> LLMResult:
        """Send prompt to Claude and return an LLMResult.

        Raises anthropic.APIError on failure so the caller can catch and log
        without crashing the worker loop.
        """
        t0 = time.monotonic()
        message = await self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        processing_ms = int((time.monotonic() - t0) * 1000)
        text = message.content[0].text if message.content else ""
        return LLMResult(
            text=text,
            processing_ms=processing_ms,
            input_tokens=message.usage.input_tokens,
            output_tokens=message.usage.output_tokens,
        )

    async def aclose(self) -> None:
        await self._client.close()

    async def __aenter__(self) -> AnthropicClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()
```

- [ ] **Step 1.4: Run tests**

```bash
uv run pytest tests/unit/test_anthropic_client.py -v
```

Expected: all PASS.

- [ ] **Step 1.5: Update `test_label_worker.py` mock to match new return type**

The mock in `tests/unit/test_label_worker.py` currently returns a 2-tuple:

```python
client.generate = AsyncMock(return_value=(response_text, 500))
```

Find the `_mock_client()` helper and update it:

```python
from app.llm.anthropic_client import LLMResult

def _mock_client(
    response_text: str = '{"event_type": "earnings", "polarity": "positive", "importance": 0.8, "confidence": 0.9, "one_sentence_summary": "Good results."}',
) -> MagicMock:
    client = MagicMock()
    client._model = "llama3.1:8b"
    client.generate = AsyncMock(
        return_value=LLMResult(
            text=response_text,
            processing_ms=500,
            input_tokens=120,
            output_tokens=45,
        )
    )
    return client
```

- [ ] **Step 1.6: Run full label_worker test suite**

```bash
uv run pytest tests/unit/test_label_worker.py -v
```

Expected: all PASS (LabelWorker's `_label_one` still unpacks the old tuple — it will fail here, which is fine, we fix it in Task 3).

If tests fail because `_label_one` tries to unpack `LLMResult` as a tuple, that's expected — note the failure and continue to Task 2.

- [ ] **Step 1.7: Commit what's clean so far**

```bash
git add app/llm/anthropic_client.py tests/unit/test_anthropic_client.py
git commit -m "feat(llm): add LLMResult dataclass with token counts to AnthropicClient.generate()"
```

---

## Task 2: DB migration — add token count columns to `llm_news_labels`

**Files:**
- Modify: `app/db/models/news.py`
- New: `alembic/versions/0010_llm_token_counts.py`

- [ ] **Step 2.1: Add columns to the model**

In `app/db/models/news.py`, add two fields to `LlmNewsLabel` after `processing_ms`:

```python
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

`Integer` is already imported in that file.

- [ ] **Step 2.2: Generate the migration**

```bash
uv run alembic revision --autogenerate -m "add token counts to llm_news_labels"
```

This creates a new file in `alembic/versions/`. Rename it to `0010_llm_token_counts.py` for consistency with existing naming:

```bash
mv alembic/versions/*add_token_counts*.py alembic/versions/0010_llm_token_counts.py
```

- [ ] **Step 2.3: Verify the migration looks correct**

Open `alembic/versions/0010_llm_token_counts.py` and confirm it contains:
- `op.add_column('llm_news_labels', sa.Column('input_tokens', sa.Integer(), nullable=True))`
- `op.add_column('llm_news_labels', sa.Column('output_tokens', sa.Integer(), nullable=True))`
- A matching `op.drop_column` in `downgrade()`

- [ ] **Step 2.4: Apply migration to test DB and verify**

```bash
uv run alembic upgrade head
uv run pytest tests/integration/test_schema.py -v
```

Expected: all PASS.

- [ ] **Step 2.5: Commit**

```bash
git add app/db/models/news.py alembic/versions/0010_llm_token_counts.py
git commit -m "feat(db): add input_tokens, output_tokens columns to llm_news_labels"
```

---

## Task 3: Update `LabelWorker` to store token counts and fire daily summary

**Files:**
- Modify: `app/ingest_news/label_worker.py`
- Modify: `tests/unit/test_label_worker.py`

- [ ] **Step 3.1: Write new failing tests**

Add to `tests/unit/test_label_worker.py`:

```python
async def test_label_worker_stores_token_counts():
    """Token counts from LLMResult must be passed to _persist_label."""
    from app.llm.anthropic_client import LLMResult

    article = MagicMock()
    article.id = 42
    article.title = "Apple raises guidance significantly above estimates"
    article.body = "Revenue beat by 12%."

    captured: list[dict] = []

    async def fake_persist(article_id, model_name, prompt_text, response_text, parsed, processing_ms, input_tokens, output_tokens):
        captured.append({"input_tokens": input_tokens, "output_tokens": output_tokens})

    client = _mock_client()
    client.generate = AsyncMock(
        return_value=LLMResult(
            text='{"event_type":"earnings","polarity":"positive","importance":0.9,"confidence":0.85,"one_sentence_summary":"Beat."}',
            processing_ms=300,
            input_tokens=88,
            output_tokens=33,
        )
    )
    worker = LabelWorker(client=client, interval_seconds=9999)
    worker._persist_label = fake_persist
    worker._fetch_unlabeled = lambda n: [article]

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(captured) == 1
    assert captured[0]["input_tokens"] == 88
    assert captured[0]["output_tokens"] == 33
```

- [ ] **Step 3.2: Run to confirm FAIL**

```bash
uv run pytest tests/unit/test_label_worker.py::test_label_worker_stores_token_counts -v
```

Expected: FAIL — `_label_one` unpacks the result as a tuple.

- [ ] **Step 3.3: Update `_label_one` in `label_worker.py`**

Change `_label_one`:

```python
async def _label_one(self, article: NewsArticle) -> None:
    prompt = build_prompt(article.title, article.body)
    result = await self._client.generate(prompt)
    parsed = parse_response(result.text)
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
    )
    log.info(
        "Labeled article %d: event_type=%s polarity=%s importance=%.2f "
        "tokens(in=%d out=%d)",
        article.id,
        parsed.get("event_type"),
        parsed.get("polarity"),
        parsed.get("importance") or 0.0,
        result.input_tokens,
        result.output_tokens,
    )
```

Update `_persist_label` signature and `_write_label`:

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
) -> None:
    with SessionLocal() as db:
        LabelWorker._write_label(
            db, article_id, model_name, prompt_text, response_text,
            parsed, processing_ms, input_tokens, output_tokens,
        )
        db.commit()
```

Update `_write_label` to accept and store the token counts:

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
        )
    )
```

- [ ] **Step 3.4: Add daily spend summary to `LabelWorker`**

Add a `_last_summary_date` field in `__init__`:

```python
self._last_summary_date: str | None = None  # "YYYY-MM-DD"
```

Add a helper method:

```python
def _maybe_send_daily_summary(self) -> None:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    if self._last_summary_date == today:
        return
    self._last_summary_date = today
    asyncio.get_event_loop().run_in_executor(None, self._send_daily_summary, today)

def _send_daily_summary(self, date_str: str) -> None:
    try:
        from app.llm.spend import daily_token_totals, estimate_cost_usd
        with SessionLocal() as db:
            totals = daily_token_totals(db, date_str)
        cost = estimate_cost_usd(totals["input_tokens"], totals["output_tokens"])
        msg = (
            f"LLM daily summary ({date_str}): "
            f"{totals['label_count']} labels, "
            f"{totals['input_tokens']:,} input tokens, "
            f"{totals['output_tokens']:,} output tokens, "
            f"~${cost:.4f} USD"
        )
        log.info(msg)
        if self._telegram is not None:
            self._telegram.send_message(msg)
    except Exception as exc:
        log.warning("Failed to send LLM daily summary: %s", exc)
```

Call `_maybe_send_daily_summary()` at the top of `run()`'s loop body, before `_process_batch()`.

- [ ] **Step 3.5: Run all label_worker tests**

```bash
uv run pytest tests/unit/test_label_worker.py -v
```

Expected: all PASS.

- [ ] **Step 3.6: Commit**

```bash
git add app/ingest_news/label_worker.py tests/unit/test_label_worker.py
git commit -m "feat(label_worker): store LLM token counts and fire daily spend summary"
```

---

## Task 4: `app/llm/spend.py` + `scripts/check_llm_spend.py`

**Files:**
- Create: `app/llm/spend.py`
- Create: `scripts/check_llm_spend.py`
- Create: `tests/unit/test_llm_spend.py`

- [ ] **Step 4.1: Write the failing test**

```python
# tests/unit/test_llm_spend.py
"""Tests for LLM spend calculation functions."""

from unittest.mock import MagicMock

from app.llm.spend import daily_token_totals, estimate_cost_usd


def _make_db(rows: list[tuple]) -> MagicMock:
    """rows: list of (label_count, input_tokens, output_tokens) from the query."""
    db = MagicMock()
    row = MagicMock()
    if rows:
        row.label_count, row.input_tokens, row.output_tokens = rows[0]
    else:
        row.label_count, row.input_tokens, row.output_tokens = 0, 0, 0
    db.execute.return_value.fetchone.return_value = row
    return db


def test_estimate_cost_usd_zero():
    assert estimate_cost_usd(0, 0) == 0.0


def test_estimate_cost_usd_known_values():
    # 1M input tokens at $0.80 + 1M output tokens at $4.00 = $4.80
    cost = estimate_cost_usd(1_000_000, 1_000_000)
    assert abs(cost - 4.80) < 0.001


def test_estimate_cost_usd_small():
    # 10k input + 5k output
    cost = estimate_cost_usd(10_000, 5_000)
    expected = (10_000 / 1_000_000 * 0.80) + (5_000 / 1_000_000 * 4.00)
    assert abs(cost - expected) < 0.0001


def test_daily_token_totals_returns_dict_with_expected_keys():
    db = _make_db([(5, 1000, 400)])
    result = daily_token_totals(db, "2026-04-25")
    assert "label_count" in result
    assert "input_tokens" in result
    assert "output_tokens" in result
    assert result["label_count"] == 5
    assert result["input_tokens"] == 1000
    assert result["output_tokens"] == 400


def test_daily_token_totals_zero_when_no_data():
    db = _make_db([(0, 0, 0)])
    result = daily_token_totals(db, "2026-04-25")
    assert result["label_count"] == 0
    assert result["input_tokens"] == 0
    assert result["output_tokens"] == 0
```

- [ ] **Step 4.2: Run to confirm FAIL**

```bash
uv run pytest tests/unit/test_llm_spend.py -v
```

Expected: `ImportError`.

- [ ] **Step 4.3: Implement `app/llm/spend.py`**

```python
# app/llm/spend.py
"""LLM cost estimation and daily token totals."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

# Claude Haiku 4.5 pricing (USD per million tokens)
_INPUT_COST_PER_MTOK = 0.80
_OUTPUT_COST_PER_MTOK = 4.00


def estimate_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Estimate Anthropic API cost in USD for a given token count."""
    return (input_tokens / 1_000_000 * _INPUT_COST_PER_MTOK) + (
        output_tokens / 1_000_000 * _OUTPUT_COST_PER_MTOK
    )


def daily_token_totals(db: Session, date_str: str) -> dict:
    """Return aggregated token counts for all LLM calls on the given date (YYYY-MM-DD).

    Excludes prefilter_skip rows (those have input_tokens=NULL or model='prefilter').
    """
    row = db.execute(
        text(
            """
            SELECT
                COUNT(*)            AS label_count,
                COALESCE(SUM(input_tokens), 0)  AS input_tokens,
                COALESCE(SUM(output_tokens), 0) AS output_tokens
            FROM llm_news_labels
            WHERE model_name != 'prefilter'
              AND DATE(created_at AT TIME ZONE 'UTC') = :date
            """
        ),
        {"date": date_str},
    ).fetchone()
    return {
        "label_count": int(row.label_count),
        "input_tokens": int(row.input_tokens),
        "output_tokens": int(row.output_tokens),
    }
```

- [ ] **Step 4.4: Implement `scripts/check_llm_spend.py`**

```python
#!/usr/bin/env python
"""Print today's LLM token usage and estimated cost.

Usage:
    uv run python scripts/check_llm_spend.py
    uv run python scripts/check_llm_spend.py --date 2026-04-20
    uv run python scripts/check_llm_spend.py --days 7
"""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta

from app.db.session import SessionLocal
from app.llm.spend import daily_token_totals, estimate_cost_usd


def _report_day(date_str: str) -> None:
    with SessionLocal() as db:
        totals = daily_token_totals(db, date_str)
    cost = estimate_cost_usd(totals["input_tokens"], totals["output_tokens"])
    print(
        f"{date_str}: {totals['label_count']} labels | "
        f"{totals['input_tokens']:>8,} in / {totals['output_tokens']:>7,} out tokens | "
        f"~${cost:.4f}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Check LLM token spend")
    parser.add_argument("--date", help="YYYY-MM-DD (default: today UTC)")
    parser.add_argument("--days", type=int, default=1, help="Report N past days (default 1)")
    args = parser.parse_args()

    if args.date:
        _report_day(args.date)
    else:
        today = datetime.now(UTC).date()
        for offset in range(args.days - 1, -1, -1):
            d = today - timedelta(days=offset)
            _report_day(d.isoformat())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4.5: Run tests**

```bash
uv run pytest tests/unit/test_llm_spend.py -v
```

Expected: all PASS.

- [ ] **Step 4.6: Run full suite and lint**

```bash
uv run pytest -q && uv run ruff check .
```

Expected: all PASS, no errors.

- [ ] **Step 4.7: Commit**

```bash
git add app/llm/spend.py scripts/check_llm_spend.py tests/unit/test_llm_spend.py
git commit -m "feat(llm): add spend.py cost calculator and check_llm_spend.py CLI script"
```

---

## Done

After all tasks complete:
- Every labeled article records `input_tokens` and `output_tokens` in `llm_news_labels`
- `scripts/check_llm_spend.py` gives an on-demand cost report per day
- `LabelWorker` sends a daily Telegram summary at the start of each new UTC day
- All existing tests pass; ruff clean
- Push and start a fresh session for the next plan
