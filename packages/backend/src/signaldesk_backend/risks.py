"""Deterministic risk flag assembly for technical-analysis outputs."""

from collections.abc import Sequence

from signaldesk_backend.indicators import (
    ConfirmationInvalidationLevels,
    DeterministicTechnicalEvent,
    RegimeClassification,
)
from signaldesk_backend.models import RiskFlag


def assess_technical_analysis_risks(
    *,
    candle_count: int,
    trend_regime: RegimeClassification,
    volatility_regime: RegimeClassification,
    volume_regime: RegimeClassification,
    technical_events: Sequence[DeterministicTechnicalEvent],
    setup_levels: ConfirmationInvalidationLevels,
    fundamentals_unavailable: bool,
) -> tuple[RiskFlag, ...]:
    """Return deterministic risk flags for already-computed TA facts.

    This function does not fetch provider data or infer unavailable enhanced
    context. It translates canonical regimes, events, setup levels, and known
    missing context into typed flags that the CLI/API can render alongside
    deterministic scores.
    """

    flags: list[RiskFlag] = [
        RiskFlag(
            kind="scope_limit",
            severity="info",
            message=(
                "This output contains deterministic technical analysis only; missing "
                "enhanced context is reported as unavailable context, not as no risk."
            ),
            source="technical_analysis_scope",
        )
    ]

    if candle_count < 50:
        flags.append(
            RiskFlag(
                kind="insufficient_history",
                severity="warning",
                message=(
                    f"Provider returned {candle_count} candle(s); some trend and setup "
                    "rules require at least 50 observations."
                ),
                source="historical_candles",
            )
        )

    for regime_name, regime in (
        ("trend", trend_regime),
        ("volatility", volatility_regime),
        ("volume", volume_regime),
    ):
        if regime.regime == "unknown":
            flags.append(
                RiskFlag(
                    kind=f"unknown_{regime_name}_regime",
                    severity="warning",
                    message=regime.reason,
                    source=regime.source_rule,
                )
            )

    if volatility_regime.regime == "high_volatility":
        flags.append(
            RiskFlag(
                kind="high_volatility",
                severity="warning",
                message=volatility_regime.reason,
                source=volatility_regime.source_rule,
            )
        )

    if volume_regime.regime == "low_volume":
        flags.append(
            RiskFlag(
                kind="liquidity",
                severity="warning",
                message=volume_regime.reason,
                source=volume_regime.source_rule,
            )
        )

    if setup_levels.invalidation is None:
        flags.append(
            RiskFlag(
                kind="missing_invalidation_level",
                severity="warning",
                message="No deterministic invalidation level is available from recent swings.",
                source="derive_confirmation_invalidation_levels",
            )
        )

    if fundamentals_unavailable:
        flags.append(
            RiskFlag(
                kind="unavailable_enhanced_context",
                severity="info",
                message=(
                    "Fundamental/catalyst context is unavailable and remains separate "
                    "from deterministic TA risk."
                ),
                source="unavailable_context",
            )
        )

    has_bullish_event = any(event.severity == "bullish" for event in technical_events)
    has_bearish_event = any(event.severity == "bearish" for event in technical_events)
    if trend_regime.regime == "downtrend" and has_bullish_event:
        flags.append(
            RiskFlag(
                kind="trend_conflict",
                severity="warning",
                message="Bullish technical events are present while the trend regime is downtrend.",
                source="technical_event_rules",
            )
        )
    if trend_regime.regime == "uptrend" and has_bearish_event:
        flags.append(
            RiskFlag(
                kind="trend_conflict",
                severity="warning",
                message="Bearish technical events are present while the trend regime is uptrend.",
                source="technical_event_rules",
            )
        )

    overextension_events = tuple(
        event for event in technical_events if event.event_type.startswith("overextension")
    )
    if overextension_events:
        flags.append(
            RiskFlag(
                kind="overextension",
                severity="warning",
                message=(
                    f"{len(overextension_events)} deterministic overextension event(s) "
                    "are present."
                ),
                source="detect_overextension_events",
            )
        )

    return tuple(flags)
