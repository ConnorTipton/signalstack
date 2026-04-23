"""Scorer — weighted signal scoring (§14) with cap rules and rejection tracking.

Accepts Detector A/B/C event triplets (via ScoringInput) and returns a
ScoringResult that maps directly to a SignalCandidate row.

Score breakdown (total 0–100):
  news quality        0–35
  price confirmation  0–30
  options abnormality 0–20
  liquidity quality   0–10  (caller-supplied; defaults to 5.0 until Phase 6)
  data confidence     0–5

Grade thresholds (§14):
  A  ≥ 82  →  status "promoted"  (high-priority)
  B  72–81 →  status "promoted"  (valid)
  C  65–71 →  status "watch"
  D  < 65  →  status "rejected"

Caps applied after raw scoring:
  proxy_cap  — proxy-mode options without (Tier-1 news + strong price): max "B"
  tier3_cap  — Tier-3 news without exceptional price + options evidence: max "C"
  conf_cap   — provider_confidence < 0.50: max "B"

rejection_reason is set whenever status=="rejected" OR a cap was applied (for
transparency even on promoted/watch candidates).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.db.models.provider import ProviderHealth
from app.db.models.signals import DetectedEvent, SignalCandidate
from app.db.session import SessionLocal

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 10.0
_DEFAULT_BATCH = 50
_WINDOW_MINUTES = 30  # wait this long after news before scoring

# Scoring weights
_NEWS_MAX = 35.0
_PRICE_MAX = 30.0
_OPTIONS_MAX = 20.0
_LIQUIDITY_MAX = 10.0
_DATA_CONF_MAX = 5.0

# Default liquidity until Phase 6 contract selector provides real values
_DEFAULT_LIQUIDITY = 5.0

# Grade thresholds
_GRADE_A_MIN = 82.0
_GRADE_B_MIN = 72.0
_GRADE_C_MIN = 65.0

# Cap thresholds
_PROXY_CAP_MAX = "B"
_TIER3_CAP_MAX = "C"
_WEAK_CONF_CAP_MAX = "B"
_WEAK_PROVIDER_THRESHOLD = 0.50
_STRONG_PRICE_CONF = 0.70  # used to exempt proxy cap when price is strong

# News tier → score weight multiplier
_TIER_FACTOR: dict[int, float] = {1: 1.0, 2: 0.8, 3: 0.5}

# Market data provider tier weight (Tradier=primary, Alpaca=fallback)
_PROVIDER_TIER_WEIGHT: dict[str, float] = {"tradier": 1.0, "alpaca": 0.75}

# Grade ordering for cap comparisons (higher rank = better grade)
_GRADE_RANK: dict[str, int] = {"A": 4, "B": 3, "C": 2, "D": 1}


# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass
class ScoringInput:
    news_event: DetectedEvent
    price_event: DetectedEvent | None
    options_event: DetectedEvent | None
    provider_confidence: float
    liquidity_score: float = field(default=_DEFAULT_LIQUIDITY)


@dataclass
class ScoringResult:
    news_score: float
    price_score: float
    options_score: float
    liquidity_score: float
    data_confidence_score: float
    score: float
    grade: str  # "A" | "B" | "C" | "D"
    status: str  # "promoted" | "watch" | "rejected"
    rejection_reason: str | None


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class SignalScorer:
    """Stateless signal scorer.

    Call score() with a ScoringInput.  Returns a ScoringResult with all
    sub-scores, the final grade (after caps), status, and rejection_reason.
    """

    def score(self, inp: ScoringInput) -> ScoringResult:
        news_s = self._news_score(inp.news_event)
        price_s = self._price_score(inp.price_event)
        opts_s = self._options_score(inp.options_event)
        liq_s = min(_LIQUIDITY_MAX, inp.liquidity_score)
        data_s = inp.provider_confidence * _DATA_CONF_MAX

        total = news_s + price_s + opts_s + liq_s + data_s
        raw_grade = self._grade_from_score(total)
        grade, cap_reason = self._apply_caps(raw_grade, inp)
        status, rejection_reason = self._resolve_outcome(grade, inp, cap_reason)

        return ScoringResult(
            news_score=round(news_s, 2),
            price_score=round(price_s, 2),
            options_score=round(opts_s, 2),
            liquidity_score=round(liq_s, 2),
            data_confidence_score=round(data_s, 2),
            score=round(total, 2),
            grade=grade,
            status=status,
            rejection_reason=rejection_reason,
        )

    @staticmethod
    def _news_score(event: DetectedEvent) -> float:
        conf = float(event.confidence or 0.0)
        imp = float(event.importance or 0.0)
        tier = event.source_tier or 2
        return conf * imp * _TIER_FACTOR.get(tier, 0.5) * _NEWS_MAX

    @staticmethod
    def _price_score(event: DetectedEvent | None) -> float:
        if event is None:
            return 0.0
        return float(event.confidence or 0.0) * float(event.importance or 0.0) * _PRICE_MAX

    @staticmethod
    def _options_score(event: DetectedEvent | None) -> float:
        if event is None:
            return 0.0
        mode = (event.metadata_json or {}).get("mode", "proxy")
        mode_factor = 1.0 if mode == "full" else 0.75
        return (
            float(event.confidence or 0.0)
            * float(event.importance or 0.0)
            * mode_factor
            * _OPTIONS_MAX
        )

    @staticmethod
    def _grade_from_score(score: float) -> str:
        if score >= _GRADE_A_MIN:
            return "A"
        if score >= _GRADE_B_MIN:
            return "B"
        if score >= _GRADE_C_MIN:
            return "C"
        return "D"

    @staticmethod
    def _apply_caps(raw_grade: str, inp: ScoringInput) -> tuple[str, str | None]:
        """Return (final_grade, cap_reason).  cap_reason is None when no cap fires."""
        grade = raw_grade
        cap_reason: str | None = None

        # Cap 1: proxy-mode options data without strong supporting evidence
        if inp.options_event is not None:
            mode = (inp.options_event.metadata_json or {}).get("mode", "proxy")
            if mode == "proxy":
                news_tier1 = (inp.news_event.source_tier or 2) == 1
                price_conf = float(inp.price_event.confidence or 0.0) if inp.price_event else 0.0
                if (
                    not (news_tier1 and price_conf >= _STRONG_PRICE_CONF)
                    and _GRADE_RANK[grade] > _GRADE_RANK[_PROXY_CAP_MAX]
                ):
                    grade = _PROXY_CAP_MAX
                    cap_reason = "options data only suggestive"

        # Cap 2: Tier-3 news without exceptional price + options confirmation
        tier = inp.news_event.source_tier or 2
        if tier >= 3:
            price_conf = float(inp.price_event.confidence or 0.0) if inp.price_event else 0.0
            opts_conf = float(inp.options_event.confidence or 0.0) if inp.options_event else 0.0
            if (
                not (price_conf > 0.80 and opts_conf > 0.70)
                and _GRADE_RANK[grade] > _GRADE_RANK[_TIER3_CAP_MAX]
            ):
                grade = _TIER3_CAP_MAX
                cap_reason = cap_reason or "weak catalyst"

        # Cap 3: weak provider confidence
        if (
            inp.provider_confidence < _WEAK_PROVIDER_THRESHOLD
            and _GRADE_RANK[grade] > _GRADE_RANK[_WEAK_CONF_CAP_MAX]
        ):
            grade = _WEAK_CONF_CAP_MAX
            cap_reason = cap_reason or "provider confidence too low"

        return grade, cap_reason

    @staticmethod
    def _primary_rejection_reason(inp: ScoringInput) -> str:
        """Infer why the raw score was below threshold."""
        news_conf = float(inp.news_event.confidence or 0.0)
        news_imp = float(inp.news_event.importance or 0.0)
        if news_conf * news_imp < 0.35:
            return "weak catalyst"
        if inp.price_event is None:
            return "no price confirmation"
        if inp.options_event is None:
            return "options activity not unusual enough"
        return "weak catalyst"

    def _resolve_outcome(
        self,
        grade: str,
        inp: ScoringInput,
        cap_reason: str | None,
    ) -> tuple[str, str | None]:
        """Return (status, rejection_reason)."""
        if grade == "D":
            reason = cap_reason or self._primary_rejection_reason(inp)
            return "rejected", reason
        if grade == "C":
            return "watch", cap_reason
        # grade "A" or "B"
        return "promoted", cap_reason


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class ScoringWorker:
    """Async loop that drives SignalScorer on a fixed interval.

    Parameters
    ----------
    scorer:
        SignalScorer instance. Defaults to a plain SignalScorer().
    interval_seconds:
        Seconds between scoring cycles. Default 30.
    batch_size:
        Max news events to score per cycle. Default 50.
    window_minutes:
        Minimum age (minutes) of a news event before scoring — gives Detectors
        B and C time to run first. Default 30.
    market_provider:
        Provider name used to look up provider_confidence. Default "tradier".
    """

    def __init__(
        self,
        scorer: SignalScorer | None = None,
        *,
        interval_seconds: float = _DEFAULT_INTERVAL,
        batch_size: int = _DEFAULT_BATCH,
        window_minutes: int = _WINDOW_MINUTES,
        market_provider: str = "tradier",
    ) -> None:
        self._scorer = scorer or SignalScorer()
        self._interval = interval_seconds
        self._batch_size = batch_size
        self._window_minutes = window_minutes
        self._market_provider = market_provider

    async def run(self) -> None:
        """Main loop: score, sleep, repeat until cancelled."""
        while True:
            t0 = datetime.now(UTC)
            try:
                count = await asyncio.to_thread(self._run_once_in_session)
                if count:
                    log.info("ScoringWorker: wrote %d signal_candidate(s)", count)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("ScoringWorker cycle error: %s", exc)
            elapsed = (datetime.now(UTC) - t0).total_seconds()
            await asyncio.sleep(max(0.0, self._interval - elapsed))

    def _run_once_in_session(self) -> int:
        with SessionLocal() as db:
            return self.run_once(db)

    def run_once(self, db: Session) -> int:
        """Score all eligible news events and write signal_candidates.

        Returns the number of candidates written.
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=self._window_minutes)
        provider_confidence = self._get_provider_confidence(db)
        news_events = self._fetch_unscored_news_events(db, cutoff, batch_size=self._batch_size)
        count = 0
        for news_event in news_events:
            price_event = self._fetch_price_event(
                db, news_event.news_article_id, news_event.symbol_id
            )
            options_event = self._fetch_options_event(
                db, news_event.news_article_id, news_event.symbol_id
            )
            inp = ScoringInput(
                news_event=news_event,
                price_event=price_event,
                options_event=options_event,
                provider_confidence=provider_confidence,
            )
            result = self._scorer.score(inp)
            db.add(self._build_signal_candidate(inp, result, now))
            count += 1
        db.commit()
        return count

    # ------------------------------------------------------------------
    # Pure helper — testable without a DB
    # ------------------------------------------------------------------

    @staticmethod
    def _build_signal_candidate(
        inp: ScoringInput,
        result: ScoringResult,
        now: datetime,
    ) -> SignalCandidate:
        return SignalCandidate(
            symbol_id=inp.news_event.symbol_id,
            ticker=inp.news_event.ticker,
            news_event_id=inp.news_event.id,
            price_event_id=inp.price_event.id if inp.price_event else None,
            options_event_id=inp.options_event.id if inp.options_event else None,
            score=result.score,
            news_score=result.news_score,
            price_score=result.price_score,
            options_score=result.options_score,
            liquidity_score=result.liquidity_score,
            data_confidence_score=result.data_confidence_score,
            provider_confidence=inp.provider_confidence,
            grade=result.grade,
            status=result.status,
            rejection_reason=result.rejection_reason,
            promoted_at=now if result.status == "promoted" else None,
            rejected_at=now if result.status == "rejected" else None,
            runtime_mode=None,
        )

    # ------------------------------------------------------------------
    # DB queries — override in tests to avoid a live session
    # ------------------------------------------------------------------

    def _get_provider_confidence(self, db: Session) -> float:
        row = (
            db.query(ProviderHealth)
            .filter(
                ProviderHealth.provider_name == self._market_provider,
                ProviderHealth.is_healthy.is_(True),
            )
            .order_by(ProviderHealth.checked_at.desc())
            .first()
        )
        if row and row.provider_confidence is not None:
            tier_weight = _PROVIDER_TIER_WEIGHT.get(self._market_provider, 0.5)
            return float(row.provider_confidence) * tier_weight
        return 0.0

    @staticmethod
    def _fetch_unscored_news_events(
        db: Session,
        cutoff: datetime,
        batch_size: int = _DEFAULT_BATCH,
    ) -> list[DetectedEvent]:
        """Return Detector A events whose window has closed and have no signal_candidate yet."""
        already_scored = (
            db.query(SignalCandidate.id)
            .filter(SignalCandidate.news_event_id == DetectedEvent.id)
            .exists()
        )
        return (
            db.query(DetectedEvent)
            .filter(
                DetectedEvent.detector == "A",
                DetectedEvent.news_article_id.isnot(None),
                DetectedEvent.detected_at < cutoff,
                ~already_scored,
            )
            .order_by(DetectedEvent.detected_at)
            .limit(batch_size)
            .all()
        )

    @staticmethod
    def _fetch_price_event(
        db: Session,
        news_article_id: int,
        symbol_id: int,
    ) -> DetectedEvent | None:
        return (
            db.query(DetectedEvent)
            .filter(
                DetectedEvent.detector == "B",
                DetectedEvent.news_article_id == news_article_id,
                DetectedEvent.symbol_id == symbol_id,
            )
            .first()
        )

    @staticmethod
    def _fetch_options_event(
        db: Session,
        news_article_id: int,
        symbol_id: int,
    ) -> DetectedEvent | None:
        return (
            db.query(DetectedEvent)
            .filter(
                DetectedEvent.detector == "C",
                DetectedEvent.news_article_id == news_article_id,
                DetectedEvent.symbol_id == symbol_id,
            )
            .first()
        )
