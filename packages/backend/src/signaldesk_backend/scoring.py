"""Deterministic score assembly for technical-analysis outputs."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from signaldesk_backend.indicators import (
    ConfirmationInvalidationLevel,
    ConfirmationInvalidationLevels,
    DeterministicTechnicalEvent,
    RegimeClassification,
)
from signaldesk_backend.models import ScoreBreakdown, ScoreReason


def score_technical_analysis(
    *,
    candle_count: int,
    latest_candle_timestamp: datetime | None = None,
    as_of: datetime | None = None,
    stale_after: timedelta = timedelta(days=7),
    trend_regime: RegimeClassification,
    volatility_regime: RegimeClassification,
    volume_regime: RegimeClassification,
    technical_events: Sequence[DeterministicTechnicalEvent],
    setup_levels: ConfirmationInvalidationLevels,
    fundamentals_unavailable: bool,
) -> tuple[ScoreBreakdown, ...]:
    """Return deterministic setup, risk, and data-quality scores with reasons.

    Scores are bounded from 0 to 100 and are intentionally simple, traceable
    rules over already-computed technical facts. They do not fetch provider data,
    infer missing context, or encode recommendations.
    """

    setup_score, setup_reasons = _setup_quality_score(
        trend_regime=trend_regime,
        technical_events=technical_events,
        setup_levels=setup_levels,
    )
    risk_score, risk_reasons = _risk_score(
        trend_regime=trend_regime,
        volatility_regime=volatility_regime,
        volume_regime=volume_regime,
        technical_events=technical_events,
        setup_levels=setup_levels,
    )
    data_quality_score, data_quality_reasons = _data_quality_score(
        candle_count=candle_count,
        latest_candle_timestamp=latest_candle_timestamp,
        as_of=as_of,
        stale_after=stale_after,
        trend_regime=trend_regime,
        volatility_regime=volatility_regime,
        volume_regime=volume_regime,
        fundamentals_unavailable=fundamentals_unavailable,
    )
    return (
        ScoreBreakdown(
            category="setup_quality",
            score=_bounded_score(setup_score),
            reasons=tuple(setup_reasons),
        ),
        ScoreBreakdown(
            category="risk",
            score=_bounded_score(risk_score),
            reasons=tuple(risk_reasons),
        ),
        ScoreBreakdown(
            category="data_quality",
            score=_bounded_score(data_quality_score),
            reasons=tuple(data_quality_reasons),
        ),
    )


def _setup_quality_score(
    *,
    trend_regime: RegimeClassification,
    technical_events: Sequence[DeterministicTechnicalEvent],
    setup_levels: ConfirmationInvalidationLevels,
) -> tuple[Decimal, list[ScoreReason]]:
    score = Decimal("50")
    reasons = [
        ScoreReason(
            code="deterministic_baseline",
            message="Setup quality starts from a neutral deterministic baseline.",
            source="deterministic_ta",
            weight=Decimal("0.20"),
        )
    ]
    if trend_regime.regime == "uptrend":
        score += Decimal("20")
        reasons.append(
            ScoreReason(
                code="trend_alignment_uptrend",
                message="Trend regime is uptrend, improving setup quality.",
                source=trend_regime.source_rule,
                weight=Decimal("0.20"),
            )
        )
    elif trend_regime.regime == "downtrend":
        score -= Decimal("20")
        reasons.append(
            ScoreReason(
                code="trend_alignment_downtrend",
                message="Trend regime is downtrend, reducing bullish setup quality.",
                source=trend_regime.source_rule,
                weight=Decimal("0.20"),
            )
        )
    else:
        reasons.append(
            ScoreReason(
                code="trend_alignment_unconfirmed",
                message=(
                    f"Trend regime is {trend_regime.regime}; "
                    "no directional setup boost is applied."
                ),
                source=trend_regime.source_rule,
                weight=Decimal("0.20"),
            )
        )
    if setup_levels.confirmation is not None:
        score += Decimal("10")
        reasons.append(
            ScoreReason(
                code="confirmation_level_available",
                message="A deterministic confirmation level is available.",
                source=setup_levels.confirmation.source_rule,
                weight=Decimal("0.10"),
            )
        )
    else:
        reasons.append(
            ScoreReason(
                code="confirmation_level_unavailable",
                message="No deterministic confirmation level is available from recent swings.",
                source="derive_confirmation_invalidation_levels",
                weight=Decimal("0.10"),
            )
        )
    if setup_levels.invalidation is not None:
        score += Decimal("10")
        reasons.append(
            ScoreReason(
                code="invalidation_level_available",
                message="A deterministic invalidation level is available.",
                source=setup_levels.invalidation.source_rule,
                weight=Decimal("0.10"),
            )
        )
    else:
        reasons.append(
            ScoreReason(
                code="invalidation_level_unavailable",
                message="No deterministic invalidation level is available from recent swings.",
                source="derive_confirmation_invalidation_levels",
                weight=Decimal("0.10"),
            )
        )
    bullish_events = sum(1 for event in technical_events if event.severity == "bullish")
    bearish_events = sum(1 for event in technical_events if event.severity == "bearish")
    if bullish_events:
        score += min(Decimal("10"), Decimal(bullish_events * 5))
        reasons.append(
            ScoreReason(
                code="bullish_technical_events",
                message=f"{bullish_events} bullish deterministic technical event(s) are present.",
                source="technical_event_rules",
                weight=Decimal("0.10"),
            )
        )
    if bearish_events:
        score -= min(Decimal("10"), Decimal(bearish_events * 5))
        reasons.append(
            ScoreReason(
                code="bearish_technical_events",
                message=f"{bearish_events} bearish deterministic technical event(s) are present.",
                source="technical_event_rules",
                weight=Decimal("0.10"),
            )
        )
    return score, reasons


def _risk_score(
    *,
    trend_regime: RegimeClassification,
    volatility_regime: RegimeClassification,
    volume_regime: RegimeClassification,
    technical_events: Sequence[DeterministicTechnicalEvent],
    setup_levels: ConfirmationInvalidationLevels,
) -> tuple[Decimal, list[ScoreReason]]:
    score = Decimal("20")
    reasons = [
        ScoreReason(
            code="technical_only_scope_limit",
            message="Risk score includes a baseline because this CLI path is TA-only.",
            source="scope_limit",
            weight=Decimal("0.20"),
        )
    ]
    for regime_name, regime in (
        ("trend", trend_regime),
        ("volatility", volatility_regime),
        ("volume", volume_regime),
    ):
        if regime.regime == "unknown":
            score += Decimal("15")
            reasons.append(
                ScoreReason(
                    code=f"unknown_{regime_name}_regime",
                    message=f"{regime_name.title()} regime is unknown, increasing risk.",
                    source=regime.source_rule,
                    weight=Decimal("0.15"),
                )
            )
    if volatility_regime.regime == "high_volatility":
        score += Decimal("15")
        reasons.append(
            ScoreReason(
                code="high_volatility_risk",
                message="Volatility regime is high_volatility, increasing setup risk.",
                source=volatility_regime.source_rule,
                weight=Decimal("0.15"),
            )
        )
    if volume_regime.regime == "low_volume":
        score += Decimal("10")
        reasons.append(
            ScoreReason(
                code="liquidity_risk_low_volume",
                message="Volume regime is low_volume, increasing liquidity risk.",
                source=volume_regime.source_rule,
                weight=Decimal("0.10"),
            )
        )
    if setup_levels.invalidation is None:
        score += Decimal("10")
        reasons.append(
            ScoreReason(
                code="missing_invalidation_level",
                message="No deterministic invalidation level is available, increasing risk.",
                source="derive_confirmation_invalidation_levels",
                weight=Decimal("0.10"),
            )
        )
    warning_events = sum(1 for event in technical_events if event.severity == "warning")
    if warning_events:
        score += min(Decimal("20"), Decimal(warning_events * 10))
        reasons.append(
            ScoreReason(
                code="warning_technical_events",
                message=f"{warning_events} warning deterministic technical event(s) are present.",
                source="technical_event_rules",
                weight=Decimal("0.20"),
            )
        )
    return score, reasons


def _data_quality_score(
    *,
    candle_count: int,
    latest_candle_timestamp: datetime | None,
    as_of: datetime | None,
    stale_after: timedelta,
    trend_regime: RegimeClassification,
    volatility_regime: RegimeClassification,
    volume_regime: RegimeClassification,
    fundamentals_unavailable: bool,
) -> tuple[Decimal, list[ScoreReason]]:
    score = Decimal("100")
    reasons = [
        ScoreReason(
            code="price_history_available",
            message=f"Provider returned {candle_count} historical candle(s).",
            source="historical_candles",
            weight=Decimal("0.30"),
        )
    ]
    for regime_name, regime in (
        ("trend", trend_regime),
        ("volatility", volatility_regime),
        ("volume", volume_regime),
    ):
        if regime.regime == "unknown":
            score -= Decimal("15")
            reasons.append(
                ScoreReason(
                    code=f"insufficient_history_for_{regime_name}_regime",
                    message=regime.reason,
                    source=regime.source_rule,
                    weight=Decimal("0.15"),
                )
            )
    if latest_candle_timestamp is not None:
        reference_time = as_of or datetime.now(UTC)
        latest_timestamp_is_naive = (
            latest_candle_timestamp.tzinfo is None
            or latest_candle_timestamp.utcoffset() is None
        )
        reference_time_is_naive = (
            reference_time.tzinfo is None or reference_time.utcoffset() is None
        )
        if latest_timestamp_is_naive or reference_time_is_naive:
            score -= Decimal("20")
            if latest_timestamp_is_naive:
                message = (
                    "Latest candle timestamp is timezone-naive, so data freshness "
                    "cannot be verified deterministically."
                )
            else:
                message = (
                    "Freshness reference timestamp is timezone-naive, so data "
                    "freshness cannot be verified deterministically."
                )
            reasons.append(
                ScoreReason(
                    code="unverifiable_price_history_freshness",
                    message=message,
                    source="historical_candles",
                    weight=Decimal("0.20"),
                )
            )
        elif reference_time - latest_candle_timestamp > stale_after:
            score -= Decimal("20")
            reasons.append(
                ScoreReason(
                    code="stale_price_history",
                    message=(
                        "Latest candle is older than the deterministic freshness "
                        f"threshold of {stale_after.days} day(s)."
                    ),
                    source="historical_candles",
                    weight=Decimal("0.20"),
                )
            )
    if fundamentals_unavailable:
        score -= Decimal("10")
        reasons.append(
            ScoreReason(
                code="fundamentals_unavailable",
                message=(
                    "Fundamental context is unavailable and is reported separately "
                    "from TA facts."
                ),
                source="unavailable_context",
                weight=Decimal("0.10"),
            )
        )
    return score, reasons



def classify_decision_support_signal_state(
    *,
    trend_regime: RegimeClassification,
    volume_regime: RegimeClassification,
    technical_events: Sequence[DeterministicTechnicalEvent],
    setup_levels: ConfirmationInvalidationLevels,
    scores: Sequence[ScoreBreakdown],
) -> dict[str, object]:
    setup_score = _score_breakdown_value(scores, "setup_quality")
    risk_score = _score_breakdown_value(scores, "risk")
    bullish_events = tuple(event for event in technical_events if event.severity == "bullish")
    bearish_events = tuple(event for event in technical_events if event.severity == "bearish")
    warning_events = tuple(event for event in technical_events if event.severity == "warning")
    stretched = any(
        event.event_type in {"overextension", "overextension_up"}
        or "stretch" in event.reason.lower()
        or "extended" in event.reason.lower()
        for event in warning_events
    )
    strength_score = _bounded_score(
        Decimal("50")
        + (Decimal("20") if trend_regime.regime == "uptrend" else Decimal("0"))
        - (Decimal("20") if trend_regime.regime == "downtrend" else Decimal("0"))
        + min(Decimal("15"), Decimal(len(bullish_events) * 5))
        - min(Decimal("15"), Decimal(len(bearish_events) * 5))
        + (
            Decimal("10")
            if volume_regime.regime in {"high_volume", "elevated_volume"}
            else Decimal("0")
        )
        - (Decimal("10") if volume_regime.regime == "low_volume" else Decimal("0"))
    )
    momentum_state = "neutral"
    if stretched:
        momentum_state = "stretched"
    elif len(bullish_events) > len(bearish_events) or (
        trend_regime.regime == "uptrend"
        and volume_regime.regime in {"high_volume", "elevated_volume"}
    ):
        momentum_state = "improving"
    elif len(bearish_events) > len(bullish_events) or trend_regime.regime == "downtrend":
        momentum_state = "fading"
    trend_state_by_regime = {
        "uptrend": "technically_strong",
        "downtrend": "technically_weak",
        "range_bound": "range_bound",
        "sideways": "range_bound",
        "unknown": "unavailable",
    }
    trend_state = trend_state_by_regime.get(trend_regime.regime, "range_bound")
    signal_state = "neutral_range"
    classification_reasons = [
        f"Trend regime is {trend_regime.regime} by {trend_regime.source_rule}.",
    ]
    if stretched:
        signal_state = "stretched_avoid_chasing"
        classification_reasons.append("Overextension warning indicates stretched momentum risk.")
    elif trend_regime.regime == "uptrend" and strength_score >= Decimal("70"):
        signal_state = "strong_momentum"
        classification_reasons.append("Strength score is at least 70 in an uptrend.")
    elif trend_regime.regime == "downtrend" or strength_score <= Decimal("35"):
        signal_state = "weak_deteriorating"
        classification_reasons.append("Downtrend or weak strength score indicates deterioration.")
    elif len(bullish_events) > len(bearish_events) or setup_levels.confirmation is not None:
        signal_state = "improving_needs_confirmation"
        classification_reasons.append("Bullish evidence is present but still needs confirmation.")
    else:
        classification_reasons.append(
            "No directional confirmation dominates; classify as neutral/range-bound."
        )
    if volume_regime.regime in {"high_volume", "elevated_volume", "low_volume"}:
        classification_reasons.append(f"Volume regime is {volume_regime.regime}.")
    return {
        "signal_state": signal_state,
        "momentum_state": momentum_state,
        "trend_state": trend_state,
        "strength_score": str(strength_score),
        "risk_score": str(risk_score) if risk_score is not None else None,
        "setup_quality_score": str(setup_score) if setup_score is not None else None,
        "classification_reasons": classification_reasons,
        "source_rule": "deterministic_decision_support_classification_v1",
        "decision_support_only": True,
        "not_trading_advice": True,
        "confirmation_level": _classification_level_payload(setup_levels.confirmation),
        "invalidation_level": _classification_level_payload(setup_levels.invalidation),
        "bullish_event_count": len(bullish_events),
        "bearish_event_count": len(bearish_events),
    }


def _score_breakdown_value(scores: Sequence[ScoreBreakdown], category: str) -> Decimal | None:
    for score in scores:
        if score.category == category:
            return score.score
    return None


def _classification_level_payload(
    level: ConfirmationInvalidationLevel | None,
) -> dict[str, str] | None:
    if level is None:
        return None
    return {
        "kind": level.kind,
        "price": str(level.price),
        "source_rule": level.source_rule,
        "source_level": level.source_level,
        "reason": level.reason,
    }

def _bounded_score(value: Decimal) -> Decimal:
    return min(Decimal("100"), max(Decimal("0"), value))
