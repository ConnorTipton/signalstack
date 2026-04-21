"""Unit tests for the LabelWorker control flow."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.ingest_news.label_worker import LabelWorker


def _mock_client(response_text: str = '{"event_type": "earnings", "polarity": "positive", "importance": 0.8, "confidence": 0.9, "one_sentence_summary": "Good results."}') -> MagicMock:
    client = MagicMock()
    client._model = "llama3.1:8b"
    client.generate = AsyncMock(return_value=(response_text, 500))
    return client


# ---------------------------------------------------------------------------
# run — control flow
# ---------------------------------------------------------------------------


async def test_label_worker_run_cancels_cleanly():
    worker = LabelWorker(client=_mock_client(), interval_seconds=0.01, batch_size=0)
    worker._fetch_unlabeled = lambda n: []

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_label_worker_skips_articles_failing_prefilter():
    article = MagicMock()
    article.id = 1
    article.title = "Company celebrates anniversary"
    article.body = "A fun party was held."

    client = _mock_client()
    worker = LabelWorker(client=client, interval_seconds=9999, batch_size=1)
    worker._fetch_unlabeled = lambda n: [article]
    worker._persist_label = lambda *a, **kw: None

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    client.generate.assert_not_awaited()


async def test_label_worker_calls_llm_for_matching_article():
    article = MagicMock()
    article.id = 2
    article.title = "Apple beats earnings estimates"
    article.body = "Revenue of $120B exceeded expectations."

    client = _mock_client()
    worker = LabelWorker(client=client, interval_seconds=9999, batch_size=1)
    worker._fetch_unlabeled = lambda n: [article]
    worker._persist_label = lambda *a, **kw: None

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    client.generate.assert_awaited()


async def test_label_worker_llm_error_does_not_abort_loop():
    article = MagicMock()
    article.id = 3
    article.title = "Apple beats earnings"
    article.body = "Revenue up."

    client = MagicMock()
    client._model = "claude-haiku-4-5-20251001"
    client.generate = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

    worker = LabelWorker(client=client, interval_seconds=0.01, batch_size=1)
    worker._fetch_unlabeled = lambda n: [article]

    task = asyncio.create_task(worker.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    # No unhandled exception — test passes if only CancelledError is raised
