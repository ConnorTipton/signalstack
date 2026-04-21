"""Convert raw Tradier REST responses into provider-neutral data classes."""

from datetime import UTC, date, datetime

from app.providers.base import Bar, OptionContractQuote, Quote

_SOURCE = "tradier"


def _ensure_list(value: dict | list | None) -> list:
    """Tradier returns a dict for single results and a list for multiple."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _ts_ms_to_dt(ms: int | None) -> datetime:
    if ms is None:
        return datetime.now(UTC)
    return datetime.fromtimestamp(ms / 1000, tz=UTC)


def normalize_quotes(raw: dict) -> list[Quote]:
    quotes_block = (raw.get("quotes") or {}).get("quote")
    rows = _ensure_list(quotes_block)
    result = []
    for q in rows:
        symbol = q.get("symbol", "")
        # Tradier provides bid_date / ask_date in epoch ms; use the later as timestamp.
        ts = _ts_ms_to_dt(q.get("trade_date") or q.get("bid_date"))
        result.append(
            Quote(
                symbol=symbol,
                timestamp=ts,
                bid=q.get("bid"),
                ask=q.get("ask"),
                last=q.get("last"),
                bid_size=q.get("bidsize"),
                ask_size=q.get("asksize"),
                source_name=_SOURCE,
            )
        )
    return result


def normalize_bars(symbol: str, raw: dict) -> list[Bar]:
    history = raw.get("history") or {}
    days = _ensure_list(history.get("day"))
    result = []
    for d in days:
        # Intraday bars include a "time" field; daily bars use just "date".
        date_str = d.get("date", "")
        time_str = d.get("time", "")
        if time_str:
            dt_str = f"{date_str} {time_str}"
            try:
                bar_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
            except ValueError:
                bar_time = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        else:
            bar_time = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=UTC)

        result.append(
            Bar(
                symbol=symbol,
                bar_time=bar_time,
                open=float(d.get("open", 0)),
                high=float(d.get("high", 0)),
                low=float(d.get("low", 0)),
                close=float(d.get("close", 0)),
                volume=int(d.get("volume", 0)),
                vwap=d.get("vwap"),
                source_name=_SOURCE,
            )
        )
    return result


def normalize_option_chain(raw: dict) -> list[OptionContractQuote]:
    options_block = (raw.get("options") or {}).get("option")
    rows = _ensure_list(options_block)
    result = []
    for o in rows:
        try:
            expiry = date.fromisoformat(o["expiration_date"])
        except (KeyError, ValueError):
            continue
        greeks = o.get("greeks") or {}
        result.append(
            OptionContractQuote(
                contract_symbol=o.get("symbol", ""),
                underlying=o.get("underlying", o.get("root_symbol", "")),
                expiration_date=expiry,
                strike=float(o.get("strike", 0)),
                option_type=o.get("option_type", "").lower(),
                bid=o.get("bid"),
                ask=o.get("ask"),
                bid_size=o.get("bidsize"),
                ask_size=o.get("asksize"),
                last=o.get("last"),
                open_interest=o.get("open_interest"),
                volume=o.get("volume"),
                implied_volatility=greeks.get("mid_iv") or greeks.get("smv_vol"),
                delta=greeks.get("delta"),
                source_name=_SOURCE,
            )
        )
    return result


def normalize_expirations(raw: dict) -> list[date]:
    expirations = raw.get("expirations") or {}
    dates = expirations.get("date") or []
    if isinstance(dates, str):
        dates = [dates]
    result = []
    for d in dates:
        try:
            result.append(date.fromisoformat(d))
        except ValueError:
            continue
    return result
