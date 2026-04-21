"""Contract selector — option chain filtering per §15.

Given a list of OptionContractRow snapshots (from option_quotes), selects the
single best contract for a promoted signal, or returns None when no acceptable
contract passes all quality gates (triggering a signal downgrade in the worker).

Filtering pipeline (applied in order):
  1. Direction  — calls for positive polarity, puts for negative
  2. Expiration — next-week Friday; fall back to the following Friday if empty
  3. Dead chain — reject contracts with OI == 0 AND volume == 0
  4. Strike band — ATM ± _ATM_BAND_STRIKES strikes
  5. Spread     — reject spread_pct > _MAX_SPREAD_PCT

Ranking (highest wins):
  - +1 ITM bonus (call strike ≤ underlying, put strike ≥ underlying)
  - highest combined OI + volume

Budget-stack rule: if all band contracts fail the spread filter, the selector
returns None.  The worker then downgrades the signal to "watch" with
rejection_reason "no liquid contract found" rather than forcing a bad pick.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func as sqla_func
from sqlalchemy.orm import Session

from app.db.models.market import OptionQuote, UnderlyingBar1m
from app.db.models.signals import DetectedEvent, SignalCandidate
from app.db.session import SessionLocal

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 30.0
_DEFAULT_BATCH = 50

# Spread quality gate
_MAX_SPREAD_PCT = 0.30      # reject when (ask - bid) / mid > 30%

# Strike selection band (± this many strikes from ATM)
_ATM_BAND_STRIKES = 2

# Liquidity score calibration (mirrors _LIQUIDITY_MAX = 10.0 in scoring.py)
_OI_FULL_SCORE = 500        # OI needed for full oi_factor contribution
_LIQUIDITY_MAX = 10.0


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass
class OptionContractRow:
    contract_symbol: str
    expiration_date: date
    strike: float
    option_type: str          # "call" | "put"
    bid: float | None
    ask: float | None
    open_interest: int | None
    volume: int | None


@dataclass
class ContractSelection:
    contract_symbol: str
    expiration_date: date
    strike: float
    option_type: str          # "call" | "put"
    bid: float | None
    ask: float | None
    spread_pct: float | None
    open_interest: int | None
    volume: int | None
    liquidity_score: float    # 0.0–10.0 — replaces _DEFAULT_LIQUIDITY placeholder
    selection_reason: str
    rejected: list[dict]      # [{"contract": str, "reason": str}]


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _next_week_friday(today: date) -> date:
    """Return the Friday of the ISO week immediately following today's week.

    (7 - weekday()) gives the number of days to the coming Monday:
      Mon=0 → 7, Tue=1 → 6, …, Sun=6 → 1
    Adding 4 more days lands on that Friday.
    """
    days_to_next_monday = 7 - today.weekday()
    return today + timedelta(days=days_to_next_monday + 4)


def _spread_pct(c: OptionContractRow) -> float | None:
    if c.bid is None or c.ask is None:
        return None
    mid = (c.bid + c.ask) / 2.0
    if mid <= 0:
        return None
    return (c.ask - c.bid) / mid


def _compute_liquidity_score(c: OptionContractRow, sp: float | None) -> float:
    oi_factor = min(1.0, (c.open_interest or 0) / _OI_FULL_SCORE)
    spread_factor = max(0.0, 1.0 - (sp or 0.0) / _MAX_SPREAD_PCT)
    return round((oi_factor * 0.5 + spread_factor * 0.5) * _LIQUIDITY_MAX, 2)


# ---------------------------------------------------------------------------
# Selector
# ---------------------------------------------------------------------------


class ContractSelector:
    """Stateless option contract selector.

    Call select() with a list of OptionContractRow objects, the current
    underlying price, the signal polarity, and today's date.  Returns a
    ContractSelection (chosen contract + rejected alternatives) or None when
    no acceptable contract is found.
    """

    def select(
        self,
        contracts: list[OptionContractRow],
        underlying_price: float,
        polarity: str,
        today: date,
    ) -> ContractSelection | None:
        rejected: list[dict] = []
        option_type = "call" if polarity == "positive" else "put"

        # Step 1 — direction filter
        pool: list[OptionContractRow] = []
        for c in contracts:
            if c.option_type == option_type:
                pool.append(c)
            else:
                rejected.append(
                    {"contract": c.contract_symbol, "reason": f"wrong direction ({c.option_type})"}
                )
        if not pool:
            return None

        # Step 2 — expiration filter (next-week Friday; fallback: following Friday)
        target = _next_week_friday(today)
        fallback = target + timedelta(weeks=1)
        exp_pool = [c for c in pool if c.expiration_date == target]
        if not exp_pool:
            exp_pool = [c for c in pool if c.expiration_date == fallback]
        for c in pool:
            if c not in exp_pool:
                rejected.append(
                    {"contract": c.contract_symbol, "reason": "expiration outside target window"}
                )
        if not exp_pool:
            return None

        # Step 3 — dead chain filter (keep live, but fall back to all if fully dead)
        live = [c for c in exp_pool if (c.open_interest or 0) > 0 or (c.volume or 0) > 0]
        for c in exp_pool:
            if c not in live:
                rejected.append(
                    {"contract": c.contract_symbol, "reason": "dead chain (no OI and no volume)"}
                )
        if not live:
            live = exp_pool  # edge case: keep all rather than returning None here

        # Step 4 — strike band ± _ATM_BAND_STRIKES
        strikes = sorted({c.strike for c in live})
        atm_strike = min(strikes, key=lambda s: abs(s - underlying_price))
        atm_idx = strikes.index(atm_strike)
        lo = max(0, atm_idx - _ATM_BAND_STRIKES)
        hi = min(len(strikes) - 1, atm_idx + _ATM_BAND_STRIKES)
        band = set(strikes[lo : hi + 1])
        banded = [c for c in live if c.strike in band]
        for c in live:
            if c not in banded:
                rejected.append(
                    {"contract": c.contract_symbol, "reason": "strike too far from ATM"}
                )
        if not banded:
            banded = live

        # Step 5 — spread filter
        liquid: list[OptionContractRow] = []
        for c in banded:
            sp = _spread_pct(c)
            if sp is None or sp <= _MAX_SPREAD_PCT:
                liquid.append(c)
            else:
                rejected.append(
                    {"contract": c.contract_symbol, "reason": f"wide spread ({sp:.0%})"}
                )
        if not liquid:
            return None  # budget-stack rule: downgrade signal, don't force a pick

        # Step 6 — rank: ITM bonus then highest OI+volume
        def _rank(c: OptionContractRow) -> tuple[int, int]:
            itm = int(
                (option_type == "call" and c.strike < underlying_price)
                or (option_type == "put" and c.strike > underlying_price)
            )
            return (itm, (c.open_interest or 0) + (c.volume or 0))

        best = max(liquid, key=_rank)
        sp = _spread_pct(best)
        itm_flag = _rank(best)[0]
        position_label = "ITM" if itm_flag else "ATM"

        return ContractSelection(
            contract_symbol=best.contract_symbol,
            expiration_date=best.expiration_date,
            strike=best.strike,
            option_type=best.option_type,
            bid=best.bid,
            ask=best.ask,
            spread_pct=sp,
            open_interest=best.open_interest,
            volume=best.volume,
            liquidity_score=_compute_liquidity_score(best, sp),
            selection_reason=(
                f"{position_label} {best.option_type} "
                f"{best.expiration_date} ${best.strike:.2f}; "
                f"OI={best.open_interest or 0} vol={best.volume or 0} "
                f"spread={f'{sp:.0%}' if sp is not None else 'N/A'}"
            ),
            rejected=rejected,
        )


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class ContractSelectorWorker:
    """Async loop that drives ContractSelector on promoted signal_candidates.

    Parameters
    ----------
    selector:
        ContractSelector instance. Defaults to a plain ContractSelector().
    interval_seconds:
        Seconds between cycles. Default 30.
    batch_size:
        Max signal_candidates to process per cycle. Default 50.
    """

    def __init__(
        self,
        selector: ContractSelector | None = None,
        *,
        interval_seconds: float = _DEFAULT_INTERVAL,
        batch_size: int = _DEFAULT_BATCH,
    ) -> None:
        self._selector = selector or ContractSelector()
        self._interval = interval_seconds
        self._batch_size = batch_size

    async def run(self) -> None:
        """Main loop: run selector, sleep, repeat until cancelled."""
        while True:
            t0 = datetime.now(UTC)
            try:
                with SessionLocal() as db:
                    count = self.run_once(db)
                if count:
                    log.info("ContractSelector: updated %d signal_candidate(s)", count)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("ContractSelector cycle error: %s", exc)
            elapsed = (datetime.now(UTC) - t0).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))

    def run_once(self, db: Session) -> int:
        """Process promoted candidates that have no contract assigned yet.

        Returns the number of candidates updated.
        """
        today = datetime.now(UTC).date()
        candidates = self._fetch_uncontracted_candidates(db, batch_size=self._batch_size)
        count = 0
        for candidate in candidates:
            underlying_price = self._fetch_underlying_price(db, candidate.symbol_id)
            if underlying_price is None:
                log.debug(
                    "ContractSelector: no price data for symbol_id=%d, skipping",
                    candidate.symbol_id,
                )
                continue
            contracts = self._fetch_option_quotes(db, candidate.symbol_id)
            polarity = self._get_polarity(db, candidate)
            selection = self._selector.select(contracts, underlying_price, polarity, today)
            self._apply_selection(candidate, selection, datetime.now(UTC))
            count += 1
        db.commit()
        return count

    # ------------------------------------------------------------------
    # Pure helper — testable without a DB
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_selection(
        candidate: SignalCandidate,
        selection: ContractSelection | None,
        now: datetime,
    ) -> None:
        """Write the selection (or a downgrade) onto the candidate in-place."""
        if selection is None:
            candidate.status = "watch"
            candidate.rejection_reason = "no liquid contract found"
            return
        candidate.contract_symbol = selection.contract_symbol
        candidate.contract_expiration = selection.expiration_date
        candidate.contract_strike = selection.strike
        candidate.contract_type = selection.option_type
        candidate.contract_bid = selection.bid
        candidate.contract_ask = selection.ask
        candidate.contract_spread_pct = selection.spread_pct
        candidate.contract_oi = selection.open_interest
        candidate.contract_volume = selection.volume
        candidate.liquidity_score = selection.liquidity_score
        candidate.contract_selection_reason = selection.selection_reason
        candidate.contract_rejection_json = selection.rejected
        candidate.contract_selected_at = now

    # ------------------------------------------------------------------
    # DB queries — override in tests to avoid a live session
    # ------------------------------------------------------------------

    @staticmethod
    def _fetch_uncontracted_candidates(
        db: Session,
        batch_size: int = _DEFAULT_BATCH,
    ) -> list[SignalCandidate]:
        """Return promoted candidates with no contract selected yet."""
        return (
            db.query(SignalCandidate)
            .filter(
                SignalCandidate.status == "promoted",
                SignalCandidate.contract_symbol.is_(None),
            )
            .order_by(SignalCandidate.created_at)
            .limit(batch_size)
            .all()
        )

    @staticmethod
    def _fetch_underlying_price(db: Session, symbol_id: int) -> float | None:
        row = (
            db.query(UnderlyingBar1m)
            .filter(UnderlyingBar1m.symbol_id == symbol_id)
            .order_by(UnderlyingBar1m.bar_time.desc())
            .first()
        )
        return float(row.close) if row else None

    @staticmethod
    def _fetch_option_quotes(db: Session, symbol_id: int) -> list[OptionContractRow]:
        """Return the most recent quote snapshot for each contract on the symbol."""
        latest_time = (
            db.query(sqla_func.max(OptionQuote.quote_time))
            .filter(OptionQuote.symbol_id == symbol_id)
            .scalar()
        )
        if latest_time is None:
            return []
        rows = (
            db.query(OptionQuote)
            .filter(
                OptionQuote.symbol_id == symbol_id,
                OptionQuote.quote_time == latest_time,
            )
            .all()
        )
        return [
            OptionContractRow(
                contract_symbol=r.contract_symbol,
                expiration_date=r.expiration_date,
                strike=float(r.strike),
                option_type=r.option_type,
                bid=float(r.bid) if r.bid is not None else None,
                ask=float(r.ask) if r.ask is not None else None,
                open_interest=int(r.open_interest) if r.open_interest is not None else None,
                volume=int(r.volume) if r.volume is not None else None,
            )
            for r in rows
        ]

    @staticmethod
    def _get_polarity(db: Session, candidate: SignalCandidate) -> str:
        """Return the polarity from the linked news DetectedEvent (default 'positive')."""
        if candidate.news_event_id is None:
            return "positive"
        event = (
            db.query(DetectedEvent)
            .filter(DetectedEvent.id == candidate.news_event_id)
            .first()
        )
        return (event.polarity or "positive") if event else "positive"
