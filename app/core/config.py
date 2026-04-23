from enum import Enum

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RuntimeMode(str, Enum):
    BUILD = "build"
    CORE = "core"
    UPGRADE = "upgrade"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "signalstack"
    environment: str = Field(default="local")
    runtime_mode: RuntimeMode = RuntimeMode.BUILD
    log_level: str = "INFO"
    monitored_tickers: str = "AAPL,MSFT,NVDA,TSLA,AMZN,META,GOOGL,AMD,SPY,QQQ,IWM,NFLX,AVGO,PLTR"
    rss_feeds: str = (
        "businesswire|https://feeds.businesswire.com/rss/home/?rss=G22;"
        "globenewswire|https://www.globenewswire.com/RssFeed/subjectcode/15-Major+Periodic+Reports;"
        "prnewswire|https://prnewswire.com/rss/news-releases-list.rss"
    )

    database_url: str = Field(
        default="postgresql+psycopg://signalstack:signalstack@localhost:5432/signalstack"
    )
    test_database_url: str | None = None

    tradier_api_token: str | None = None
    tradier_account_id: str | None = None
    tradier_environment: str = "sandbox"

    alpaca_api_key: str | None = None
    alpaca_secret_key: str | None = None
    alpaca_paper: bool = True

    marketaux_api_token: str | None = None

    cloud_llm_api_key: str | None = None
    claude_model: str = "claude-haiku-4-5-20251001"

    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None

    api_key: str | None = None

    alerts_dry_run: bool = True
    market_data_max_age_minutes: int = 15


settings = Settings()
