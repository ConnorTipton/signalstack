from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Index, Integer, Numeric, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (
        # Dedupe: one row per (source, provider ID) and one row per content hash.
        Index(
            "uq_news_articles_source_event_id",
            "source_name",
            "provider_event_id",
            unique=True,
            postgresql_where=text("provider_event_id IS NOT NULL"),
        ),
        Index(
            "uq_news_articles_content_hash",
            "content_hash",
            unique=True,
            postgresql_where=text("content_hash IS NOT NULL"),
        ),
        Index("ix_news_articles_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    source_name: Mapped[str] = mapped_column(String(50), nullable=False)
    source_tier: Mapped[int] = mapped_column(Integer, nullable=False)
    provider_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    provider_published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    related_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    normalization_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(nullable=False, server_default=text("false"))
    duplicate_of_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class NewsArticleTicker(Base):
    __tablename__ = "news_article_tickers"
    __table_args__ = (
        Index("uq_news_article_tickers_article_ticker", "article_id", "ticker", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    symbol_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LlmNewsLabel(Base):
    __tablename__ = "llm_news_labels"
    __table_args__ = (
        Index(
            "uq_llm_news_labels_article_model",
            "article_id",
            "model_name",
            unique=True,
            postgresql_where=text("article_id IS NOT NULL"),
            sqlite_where=text("article_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    article_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    response_text: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    polarity: Mapped[str | None] = mapped_column(String(10), nullable=True)
    importance: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    one_sentence_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    processing_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
