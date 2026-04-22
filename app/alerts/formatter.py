"""Alert formatter — §16 decision-ready template.

Builds an Alert ORM instance from a promoted SignalCandidate and renders it
to the Telegram message string.

Grade display: a trailing dash (e.g. "B-") means a quality cap was applied
but the signal still promoted.  The dash is derived from
candidate.rejection_reason being non-None on a promoted or watch candidate.
"""

from __future__ import annotations

from app.db.models.execution import Alert
from app.db.models.signals import SignalCandidate


def _grade_display(candidate: SignalCandidate) -> str:
    grade = candidate.grade or "?"
    if candidate.rejection_reason and candidate.status in ("promoted", "watch"):
        return f"{grade}-"
    return grade


def _liquidity_note(candidate: SignalCandidate) -> str:
    parts: list[str] = []
    if candidate.contract_spread_pct is not None:
        sp = float(candidate.contract_spread_pct)
        label = "tight" if sp <= 0.10 else "acceptable" if sp <= 0.20 else "wide"
        parts.append(f"spread {sp:.0%} ({label})")
    if candidate.contract_oi is not None:
        parts.append(f"OI {candidate.contract_oi:,}")
    if candidate.contract_volume is not None:
        parts.append(f"vol {candidate.contract_volume:,}")
    return "; ".join(parts) if parts else "N/A"


def _data_note(candidate: SignalCandidate) -> str:
    notes: list[str] = []
    if candidate.rejection_reason:
        notes.append(f"cap applied: {candidate.rejection_reason}")
    return "; ".join(notes) if notes else "no caveats"


def _render_contract(alert: Alert) -> str:
    if alert.expiration_date and alert.strike and alert.option_type:
        return f"{alert.expiration_date} ${float(alert.strike):.2f} {alert.option_type}"
    return "N/A"


class AlertFormatter:
    """Stateless — builds Alert ORM instances and renders them to Telegram text."""

    def build(
        self,
        candidate: SignalCandidate,
        *,
        news_summary: str | None = None,
        dry_run: bool = True,
    ) -> Alert:
        """Create an unsaved Alert from a promoted SignalCandidate."""
        direction = "bullish" if (candidate.contract_type or "") == "call" else "bearish"
        direction_word = "above" if direction == "bullish" else "below"

        reason_parts: list[str] = []
        reason_parts.append(news_summary if news_summary else "catalyst detected")
        if candidate.price_score is not None and float(candidate.price_score) > 0:
            reason_parts.append("price confirmed")
        if candidate.options_score is not None and float(candidate.options_score) > 0:
            reason_parts.append("options activity elevated")

        return Alert(
            signal_candidate_id=candidate.id,
            symbol_id=candidate.symbol_id,
            ticker=candidate.ticker,
            direction=direction,
            score=candidate.score,
            grade=_grade_display(candidate),
            contract_symbol=candidate.contract_symbol,
            expiration_date=candidate.contract_expiration,
            strike=(
                float(candidate.contract_strike) if candidate.contract_strike is not None else None
            ),
            option_type=candidate.contract_type,
            reason="; ".join(reason_parts),
            entry_condition=f"only if {candidate.ticker} holds {direction_word} breakout level",
            invalidation="lose breakout level / VWAP",
            target1="Trim at +25% option premium",
            target2="Exit remainder at +50% or end-of-day",
            time_stop="Close by 3:30 PM ET if no follow-through",
            liquidity_note=_liquidity_note(candidate),
            data_note=_data_note(candidate),
            dry_run=dry_run,
            send_attempts=0,
        )

    @staticmethod
    def render(alert: Alert) -> str:
        """Render an Alert to the §16 Telegram message string."""
        score_str = f"{float(alert.score):.0f}" if alert.score is not None else "?"
        lines = [
            f"{alert.ticker.upper()} {(alert.direction or '').upper()} | Score {score_str} | Grade {alert.grade or '?'}",
            f"Reason: {alert.reason or '—'}",
            f"Contract: {_render_contract(alert)}",
            f"Entry: {alert.entry_condition or '—'}",
            f"Invalidation: {alert.invalidation or '—'}",
            f"Target 1: {alert.target1 or '—'}",
            f"Target 2: {alert.target2 or '—'}",
            f"Time stop: {alert.time_stop or '—'}",
            f"Liquidity: {alert.liquidity_note or '—'}",
            f"Data note: {alert.data_note or '—'}",
        ]
        if alert.dry_run:
            lines.insert(0, "[DRY RUN]")
        return "\n".join(lines)
