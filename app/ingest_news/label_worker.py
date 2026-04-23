"""LLM news labeling worker.

Polls news_articles for unlabeled, non-duplicate articles, applies the
keyword prefilter, and for matching articles calls the LLM to assign:
  event_type, polarity, importance, confidence, one_sentence_summary

Results are stored in llm_news_labels. The raw prompt + response are always
persisted so the labeling can be replayed or re-run with a different model
(blueprint §20.E).

Articles that don't pass the keyword prefilter are marked with a lightweight
``prefilter_skip`` label so they do not get re-fetched forever.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models.news import LlmNewsLabel, NewsArticle
from app.db.models.provider import ProviderHealth
from app.db.session import SessionLocal
from app.llm.anthropic_client import AnthropicClient
from app.llm.prefilter import prefilter_article
from app.llm.prompt import build_prompt, parse_response

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 60.0  # seconds between labeling cycles
_DEFAULT_BATCH = 10  # articles per cycle


class LabelWorker:
    """Async worker that labels news articles using a local LLM.

    Parameters
    ----------
    client:
        LLM client with a ``generate(prompt) -> tuple[str, int]`` async method.
        Defaults to an AnthropicClient built from settings if not provided.
    interval_seconds:
        Seconds between labeling cycles. Default 60.
    batch_size:
        Max articles to process per cycle. Default 10.
    """

    def __init__(
        self,
        client: AnthropicClient | None = None,
        *,
        interval_seconds: float = _DEFAULT_INTERVAL,
        batch_size: int = _DEFAULT_BATCH,
    ) -> None:
        if client is None:
            from app.core.config import settings

            client = AnthropicClient(
                api_key=settings.cloud_llm_api_key or "",
                model=settings.claude_model,
            )
        self._client = client
        self._interval = interval_seconds
        self._batch_size = batch_size
        self._consecutive_failures = 0
        self._last_success_at: datetime | None = None

    async def run(self) -> None:
        """Main loop: label a batch of articles, sleep, repeat until cancelled."""
        while True:
            cycle_start = datetime.now(UTC)
            try:
                await self._process_batch()
                self._consecutive_failures = 0
                self._last_success_at = datetime.now(UTC)
                await asyncio.to_thread(self._record_health, is_healthy=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._consecutive_failures += 1
                await asyncio.to_thread(self._record_health, is_healthy=False, error=str(exc))
            elapsed = (datetime.now(UTC) - cycle_start).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))

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

    async def _process_batch(self) -> None:
        articles = await asyncio.to_thread(self._fetch_unlabeled, self._batch_size)
        await asyncio.gather(*[self._process_one(article) for article in articles])

    async def _process_one(self, article: NewsArticle) -> None:
        category = prefilter_article(article.title, article.body)
        if category is None:
            log.debug("Prefilter skip: article %d — %s", article.id, article.title[:60])
            await asyncio.to_thread(self._persist_prefilter_skip, article.id)
            return
        log.debug("Prefilter pass (%s): article %d", category, article.id)
        try:
            await self._label_one(article)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("LLM labeling failed for article %d: %s", article.id, exc)

    async def _label_one(self, article: NewsArticle) -> None:
        prompt = build_prompt(article.title, article.body)
        response_text, processing_ms = await self._client.generate(prompt)
        parsed = parse_response(response_text)
        await asyncio.to_thread(
            self._persist_label,
            article.id,
            self._client._model,  # noqa: SLF001
            prompt,
            response_text,
            parsed,
            processing_ms,
        )
        log.info(
            "Labeled article %d: event_type=%s polarity=%s importance=%.2f",
            article.id,
            parsed.get("event_type"),
            parsed.get("polarity"),
            parsed.get("importance") or 0.0,
        )

    @staticmethod
    def _persist_label(
        article_id: int,
        model_name: str,
        prompt_text: str,
        response_text: str,
        parsed: dict,
        processing_ms: int,
    ) -> None:
        with SessionLocal() as db:
            LabelWorker._write_label(
                db, article_id, model_name, prompt_text, response_text, parsed, processing_ms
            )
            db.commit()

    @staticmethod
    def _persist_prefilter_skip(article_id: int) -> None:
        with SessionLocal() as db:
            LabelWorker._write_prefilter_skip(db, article_id)
            db.commit()

    @staticmethod
    def _write_prefilter_skip(db: Session, article_id: int) -> None:
        existing = db.query(LlmNewsLabel).filter(LlmNewsLabel.article_id == article_id).first()
        if existing is not None:
            return
        db.add(
            LlmNewsLabel(
                article_id=article_id,
                model_name="prefilter",
                prompt_text="",
                response_text="prefilter_skip",
                event_type=None,
                polarity=None,
                importance=None,
                confidence=None,
                one_sentence_summary=None,
                processing_ms=0,
            )
        )

    @staticmethod
    def _write_label(
        db: Session,
        article_id: int,
        model_name: str,
        prompt_text: str,
        response_text: str,
        parsed: dict,
        processing_ms: int,
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
            )
        )

    @staticmethod
    def _fetch_unlabeled(batch_size: int) -> list[NewsArticle]:
        with SessionLocal() as db:
            labeled_subq = select(LlmNewsLabel.article_id).scalar_subquery()
            return (
                db.query(NewsArticle)
                .filter(
                    ~NewsArticle.id.in_(labeled_subq),
                    NewsArticle.is_duplicate.is_(False),
                )
                .order_by(NewsArticle.id)
                .limit(batch_size)
                .all()
            )
