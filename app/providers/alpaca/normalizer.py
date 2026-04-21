"""Convert raw Alpaca market-data REST responses into provider-neutral data classes."""

import re
from datetime import UTC, date, datetime

from app.providers.base import Bar, OptionContractQuote, Quote

_SOURCE = "alpaca"

# OCC option symbol format: {underlying}{YYMMDD}{C|P}{strike*1000 zero-padded to 8 digits}
# e.g. AAPL241206C00180000 → AAPL, 2024-12-06, call, 180.00
_OCC_RE = re.compile(
    r"^(?P<underlying>[A-Z]+)(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<type>[CP])(?P<strike>\d{8})$"
)


def _parse_occ(contract_symbol: str) -> tuple[str, date, str, float] | None:
    m = _OCC_RE.match(contract_symbol)
    if not m:
        return None
    underlying = m.group("underlying")
    expiry = date(2000 + int(m.group("yy")), int(m.group("mm")), int(m.group("dd")))
    option_type = "call" if m.group("type") == "C" else "put"
    strike = int(m.group("strike")) / 1000
    return underlying, expiry, option_type, strike


def _parse_ts(ts: str) -> datetime:
    """Parse an RFC3339 / ISO 8601 timestamp string to an aware datetime."""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def normalize_quotes(raw: dict) -> list[Quote]:
    quotes = raw.get("quotes") or {}
    result = []
    for symbol, q in quotes.items():
        ts = _parse_ts(q["t"]) if "t" in q else datetime.now(UTC)
        result.append(
            Quote(
                symbol=symbol,
                timestamp=ts,
                bid=q.get("bp"),
                ask=q.get("ap"),
                last=None,  # latest quote endpoint doesn't include last trade
                bid_size=q.get("bs"),
                ask_size=q.get("as"),
                source_name=_SOURCE,
            )
        )
    return result


def normalize_bars(raw: dict) -> list[Bar]:
    bars_by_symbol = raw.get("bars") or {}
    result = []
    for symbol, bar_list in bars_by_symbol.items():
        for b in bar_list or []:
            result.append(
                Bar(
                    symbol=symbol,
                    bar_time=_parse_ts(b["t"]),
                    open=float(b["o"]),
                    high=float(b["h"]),
                    low=float(b["l"]),
                    close=float(b["c"]),
                    volume=int(b["v"]),
                    vwap=b.get("vw"),
                    trade_count=b.get("n"),
                    source_name=_SOURCE,
                )
            )
    return result


def normalize_option_chain(raw: dict) -> list[OptionContractQuote]:
    snapshots = raw.get("snapshots") or {}
    result = []
    for contract_symbol, snap in snapshots.items():
        parsed = _parse_occ(contract_symbol)
        if parsed is None:
            continue
        underlying, expiry, option_type, strike = parsed
        lq = snap.get("latestQuote") or {}
        lt = snap.get("latestTrade") or {}
        greeks = snap.get("greeks") or {}
        result.append(
            OptionContractQuote(
                contract_symbol=contract_symbol,
                underlying=underlying,
                expiration_date=expiry,
                strike=strike,
                option_type=option_type,
                bid=lq.get("bp"),
                ask=lq.get("ap"),
                bid_size=lq.get("bs"),
                ask_size=lq.get("as"),
                last=lt.get("p"),
                implied_volatility=snap.get("impliedVolatility"),
                delta=greeks.get("delta"),
                source_name=_SOURCE,
            )
        )
    return result


def normalize_expirations(raw: dict) -> list[date]:
    """Parse expiration dates from Alpaca options expirations endpoint."""
    dates = raw.get("expirations") or []
    result = []
    for d in dates:
        try:
            result.append(date.fromisoformat(d))
        except ValueError:
            continue
    return result
