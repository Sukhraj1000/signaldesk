from datetime import UTC, datetime
from decimal import Decimal

from signaldesk_backend import (
    ConfirmationInvalidationLevel,
    ConfirmationInvalidationLevels,
    DeterministicTechnicalEvent,
    RegimeClassification,
    assess_technical_analysis_risks,
)

NOW = datetime(2026, 1, 15, tzinfo=UTC)


def test_assess_technical_analysis_risks_flags_insufficient_history_and_missing_context() -> None:
    flags = assess_technical_analysis_risks(
        candle_count=40,
        trend_regime=RegimeClassification(
            regime="unknown",
            source_rule="insufficient_history_for_trend_regime",
            reason="Need at least 50 closes to classify trend; received 40.",
        ),
        volatility_regime=RegimeClassification(
            regime="unknown",
            source_rule="insufficient_history_for_volatility_regime",
            reason="Need at least 64 candles to classify volatility; received 40.",
        ),
        volume_regime=RegimeClassification(
            regime="normal_volume",
            source_rule="latest_volume_within_prior_average_band",
            reason="Latest volume is normal.",
        ),
        technical_events=(),
        setup_levels=ConfirmationInvalidationLevels(confirmation=None, invalidation=None),
        fundamentals_unavailable=True,
    )

    assert [flag.kind for flag in flags] == [
        "scope_limit",
        "insufficient_history",
        "unknown_trend_regime",
        "unknown_volatility_regime",
        "missing_invalidation_level",
        "unavailable_enhanced_context",
    ]
    assert [flag.severity for flag in flags] == [
        "info",
        "warning",
        "warning",
        "warning",
        "warning",
        "info",
    ]
    assert flags[2].source == "insufficient_history_for_trend_regime"


def test_assess_technical_analysis_risks_flags_liquidity_volatility_events() -> None:
    flags = assess_technical_analysis_risks(
        candle_count=120,
        trend_regime=RegimeClassification(
            regime="uptrend",
            source_rule="close_above_short_sma_above_long_sma",
            reason="Latest close is above aligned moving averages.",
        ),
        volatility_regime=RegimeClassification(
            regime="high_volatility",
            source_rule="latest_atr_above_trailing_baseline_band",
            reason="Latest ATR is above its trailing baseline band.",
        ),
        volume_regime=RegimeClassification(
            regime="low_volume",
            source_rule="latest_volume_below_prior_average_band",
            reason="Latest volume is below 0.75x its prior trailing average.",
        ),
        technical_events=(
            DeterministicTechnicalEvent(
                event_type="overextension_up",
                timestamp=NOW,
                candle_index=119,
                severity="warning",
                source_rule="close_far_above_ema20_by_atr_multiple",
                source_indicators=("close", "ema_20", "atr_14"),
                reason="Close is extended above EMA 20.",
                price=Decimal("120"),
                invalidation_condition="Mean reversion back toward EMA 20.",
            ),
            DeterministicTechnicalEvent(
                event_type="lost_moving_average",
                timestamp=NOW,
                candle_index=119,
                severity="bearish",
                source_rule="close_crossed_below_sma",
                source_indicators=("sma_20",),
                reason="Close moved below SMA 20.",
                price=Decimal("99"),
                invalidation_condition="A reclaim would invalidate the event.",
            ),
        ),
        setup_levels=ConfirmationInvalidationLevels(
            confirmation=ConfirmationInvalidationLevel(
                kind="confirmation",
                price=Decimal("125"),
                source_rule="nearest_resistance_above_latest_close",
                source_level="resistance_zone[125,125] touches=1",
                reason="Move through resistance confirms upside continuation.",
            ),
            invalidation=ConfirmationInvalidationLevel(
                kind="invalidation",
                price=Decimal("100"),
                source_rule="nearest_support_below_latest_close",
                source_level="support_zone[100,100] touches=1",
                reason="Break below support invalidates the setup.",
            ),
        ),
        fundamentals_unavailable=False,
    )

    flags_by_kind = {flag.kind: flag for flag in flags}
    assert flags_by_kind["high_volatility"].source == "latest_atr_above_trailing_baseline_band"
    assert flags_by_kind["liquidity"].source == "latest_volume_below_prior_average_band"
    assert flags_by_kind["trend_conflict"].message == (
        "Bearish technical events are present while the trend regime is uptrend."
    )
    assert flags_by_kind["overextension"].message == (
        "1 deterministic overextension event(s) are present."
    )
