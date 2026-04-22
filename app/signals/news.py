"""Detector A — News catalyst detector.

Polls llm_news_labels for rows that have not yet produced a detected_events
row, then emits one DetectedEvent per ticker per label.

A label is skipped when:
- event_type is None (LLM failed to produce a usable classification)

One label can yield multiple events when a news article is tagged to several
tickers (via news_article_tickers).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.db.models.news import LlmNewsLabel, NewsArticle, NewsArticleTicker
from app.db.models.signals import DetectedEvent
from app.db.session import SessionLocal

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 30.0
_DEFAULT_BATCH = 50


class NewsDetector:
    """Stateless detector that converts LLM labels into detected_events rows.

    All methods that touch the DB accept a Session so they can be tested
    without a real database by patching the individual fetch methods.
    """

    def run_once(self, db: Session) -> int:
        """Emit DetectedEvent rows for all unprocessed LLM labels.

        Returns the number of events written.
        """
        labels = self._fetch_undetected(db)
        count = 0
        for label in labels:
            if not self._is_usable(label):
                log.debug("Skipping label %d — event_type is None", label.id)
                continue
            article = db.get(NewsArticle, label.article_id)
            tickers = self._fetch_tickers(db, label.article_id)
            if not tickers:
                log.debug(
                    "Skipping label %d — no tickers mapped to article %d",
                    label.id,
                    label.article_id,
                )
                continue
            for ticker_row in tickers:
                db.add(self._build_event(label, article, ticker_row))
                count += 1
        db.commit()
        return count

    # ------------------------------------------------------------------
    # Pure helpers — testable without a DB
    # ------------------------------------------------------------------

    @staticmethod
    def _is_usable(label: LlmNewsLabel) -> bool:
        return label.event_type is not None

    @staticmethod
    def _build_event(
        label: LlmNewsLabel,
        article: NewsArticle | None,
        ticker_row: NewsArticleTicker,
    ) -> DetectedEvent:
        return DetectedEvent(
            detector="A",
            symbol_id=ticker_row.symbol_id or 0,
            ticker=ticker_row.ticker,
            event_type=label.event_type,
            polarity=label.polarity,
            importance=float(label.importance) if label.importance is not None else None,
            confidence=float(label.confidence) if label.confidence is not None else None,
            source_tier=article.source_tier if article is not None else None,
            one_sentence_summary=label.one_sentence_summary,
            news_article_id=label.article_id,
            llm_label_id=label.id,
        )

    # ------------------------------------------------------------------
    # DB queries — override in tests to avoid a live session
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_undetected(db: Session, batch_size: int = _DEFAULT_BATCH) -> list[LlmNewsLabel]:
        detected_subq = (
            db.query(DetectedEvent.llm_label_id)
            .filter(DetectedEvent.llm_label_id.isnot(None))
            .scalar_subquery()
        )
        return (
            db.query(LlmNewsLabel)
            .filter(~LlmNewsLabel.id.in_(detected_subq))
            .order_by(LlmNewsLabel.id)
            .limit(batch_size)
            .all()
        )

    @staticmethod
    def _fetch_tickers(db: Session, article_id: int) -> list[NewsArticleTicker]:
        return db.query(NewsArticleTicker).filter(NewsArticleTicker.article_id == article_id).all()


class NewsDetectorWorker:
    """Async loop that drives NewsDetector on a fixed interval.

    Parameters
    ----------
    detector:
        NewsDetector instance. Defaults to a plain NewsDetector().
    interval_seconds:
        Seconds between detection cycles. Default 30.
    """

    def __init__(
        self,
        detector: NewsDetector | None = None,
        *,
        interval_seconds: float = _DEFAULT_INTERVAL,
    ) -> None:
        self._detector = detector or NewsDetector()
        self._interval = interval_seconds

    async def run(self) -> None:
        """Main loop: run detector, sleep, repeat until cancelled."""
        while True:
            t0 = datetime.now(UTC)
            try:
                with SessionLocal() as db:
                    count = self._detector.run_once(db)
                if count:
                    log.info("NewsDetector: emitted %d event(s)", count)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("NewsDetector cycle error: %s", exc)
            elapsed = (datetime.now(UTC) - t0).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))
