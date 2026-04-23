from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import settings
from app.signals.scoring import _GRADE_A_MIN, _GRADE_B_MIN, _GRADE_C_MIN

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingRow(BaseModel):
    section: str
    key: str
    value: str
    kind: str = "text"  # "text" | "badge"
    variant: str | None = None  # for badge: default | positive | amber | inactive


class SettingsOut(BaseModel):
    rows: list[SettingRow]


def _market_primary() -> str:
    if settings.tradier_api_token:
        return "Tradier"
    if settings.alpaca_api_key:
        return "Alpaca"
    return "none configured"


def _market_fallback() -> str:
    if settings.tradier_api_token and settings.alpaca_api_key:
        return "Alpaca"
    return "—"


def _llm_labeler() -> str:
    if settings.cloud_llm_api_key:
        return f"{settings.claude_model} (Anthropic cloud)"
    return "disabled (no API key)"


def _telegram_status() -> tuple[str, str]:
    if settings.telegram_bot_token and settings.telegram_chat_id:
        return "enabled", "positive"
    return "disabled", "inactive"


@router.get("", response_model=SettingsOut)
def get_settings() -> SettingsOut:
    """Redacted read-only view of runtime configuration.

    Never returns secrets; only whether they are set and their effect on
    provider routing / feature enablement.
    """
    tg_val, tg_variant = _telegram_status()
    rows: list[SettingRow] = [
        SettingRow(section="Runtime", key="MODE", value=settings.runtime_mode.value.capitalize(),
                   kind="badge", variant="default"),
        SettingRow(section="Runtime", key="ENVIRONMENT", value=settings.environment),
        SettingRow(section="Runtime", key="MONITORED_TICKERS",
                   value=settings.monitored_tickers.replace(",", ", ")),
        SettingRow(section="Execution", key="PAPER_ONLY",
                   value=str(settings.alpaca_paper).lower(),
                   kind="badge",
                   variant="amber" if settings.alpaca_paper else "inactive"),
        SettingRow(section="Execution", key="LIVE_TRADING",
                   value="disabled" if settings.alpaca_paper else "enabled",
                   kind="badge",
                   variant="inactive" if settings.alpaca_paper else "positive"),
        SettingRow(section="Providers", key="MARKET_PRIMARY", value=_market_primary()),
        SettingRow(section="Providers", key="MARKET_FALLBACK", value=_market_fallback()),
        SettingRow(section="Providers", key="LLM_LABELER", value=_llm_labeler()),
        SettingRow(section="Providers", key="MARKETAUX_CONFIGURED",
                   value="yes" if settings.marketaux_api_token else "no",
                   kind="badge",
                   variant="positive" if settings.marketaux_api_token else "inactive"),
        SettingRow(section="Alerts", key="TELEGRAM_ENABLED", value=tg_val,
                   kind="badge", variant=tg_variant),
        SettingRow(section="Alerts", key="DRY_RUN", value=str(settings.alerts_dry_run).lower(),
                   kind="badge",
                   variant="amber" if settings.alerts_dry_run else "positive"),
        SettingRow(section="Scoring", key="GRADE_A_MIN", value=str(_GRADE_A_MIN)),
        SettingRow(section="Scoring", key="GRADE_B_MIN_ALERT", value=str(_GRADE_B_MIN)),
        SettingRow(section="Scoring", key="GRADE_C_MIN_WATCH", value=str(_GRADE_C_MIN)),
        SettingRow(section="Data", key="MARKET_DATA_MAX_AGE_MIN",
                   value=str(settings.market_data_max_age_minutes)),
    ]
    return SettingsOut(rows=rows)
