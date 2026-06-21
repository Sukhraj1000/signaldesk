from datetime import UTC, datetime, timedelta
from decimal import Decimal

from signaldesk_backend import (
    ConfirmationInvalidationLevel,
    ConfirmationInvalidationLevels,
    DeterministicTechnicalEvent,
    RegimeClassification,
    score_technical_analysis,
)

NOW = datetime(2026, 1, 15, tzinfo=UTC)


def test_score_technical_analysis_returns_traceable_score_categories() -> None:
    scores = score_technical_analysis(
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
        technical_events=(),
        setup_levels=ConfirmationInvalidationLevels(confirmation=None, invalidation=None),
        fundamentals_unavailable=True,
    )

    assert tuple(score.category for score in scores) == (
        "setup_quality",
        "risk",
        "data_quality",
    )
    assert tuple(score.score for score in scores) == (
        Decimal("50"),
        Decimal("60"),
        Decimal("60"),
    )
    assert [reason.code for reason in scores[1].reasons] == [
        "technical_only_scope_limit",
        "unknown_trend_regime",
        "unknown_volatility_regime",
        "missing_invalidation_level",
    ]
    assert scores[2].reasons[-1].code == "fundamentals_unavailable"


def test_score_technical_analysis_reduces_data_quality_for_stale_price_history() -> None:
    scores = score_technical_analysis(
        candle_count=120,
        latest_candle_timestamp=NOW - timedelta(days=12),
        as_of=NOW,
        stale_after=timedelta(days=7),
        trend_regime=RegimeClassification(
            regime="uptrend",
            source_rule="close_above_short_sma_above_long_sma",
            reason="Latest close is above aligned moving averages.",
        ),
        volatility_regime=RegimeClassification(
            regime="normal_volatility",
            source_rule="latest_atr_within_trailing_baseline_band",
            reason="Latest ATR is normal.",
        ),
        technical_events=(),
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

    data_quality = next(score for score in scores if score.category == "data_quality")
    assert data_quality.score == Decimal("80")
    assert data_quality.reasons[-1].code == "stale_price_history"
    assert data_quality.reasons[-1].source == "historical_candles"
    assert data_quality.reasons[-1].message == (
        "Latest candle is older than the deterministic freshness threshold of 7 day(s)."
    )


def test_score_technical_analysis_reduces_data_quality_for_unverifiable_naive_timestamp() -> None:
    scores = score_technical_analysis(
        candle_count=120,
        latest_candle_timestamp=datetime(2026, 1, 15),
        as_of=NOW,
        trend_regime=RegimeClassification(
            regime="uptrend",
            source_rule="close_above_short_sma_above_long_sma",
            reason="Latest close is above aligned moving averages.",
        ),
        volatility_regime=RegimeClassification(
            regime="normal_volatility",
            source_rule="latest_atr_within_trailing_baseline_band",
            reason="Latest ATR is normal.",
        ),
        technical_events=(),
        setup_levels=ConfirmationInvalidationLevels(confirmation=None, invalidation=None),
        fundamentals_unavailable=False,
    )

    data_quality = next(score for score in scores if score.category == "data_quality")
    assert data_quality.score == Decimal("80")
    assert data_quality.reasons[-1].code == "unverifiable_price_history_freshness"


def test_score_technical_analysis_reduces_data_quality_for_unverifiable_naive_as_of() -> None:
    scores = score_technical_analysis(
        candle_count=120,
        latest_candle_timestamp=NOW - timedelta(days=12),
        as_of=datetime(2026, 1, 15),
        stale_after=timedelta(days=7),
        trend_regime=RegimeClassification(
            regime="uptrend",
            source_rule="close_above_short_sma_above_long_sma",
            reason="Latest close is above aligned moving averages.",
        ),
        volatility_regime=RegimeClassification(
            regime="normal_volatility",
            source_rule="latest_atr_within_trailing_baseline_band",
            reason="Latest ATR is normal.",
        ),
        technical_events=(),
        setup_levels=ConfirmationInvalidationLevels(confirmation=None, invalidation=None),
        fundamentals_unavailable=False,
    )

    data_quality = next(score for score in scores if score.category == "data_quality")
    assert data_quality.score == Decimal("80")
    assert data_quality.reasons[-1].code == "unverifiable_price_history_freshness"
    assert data_quality.reasons[-1].message == (
        "Freshness reference timestamp is timezone-naive, so data freshness "
        "cannot be verified deterministically."
    )


def test_score_technical_analysis_bounds_scores_and_uses_event_reasons() -> None:
    warning_events = tuple(
        DeterministicTechnicalEvent(
            event_type="overextension_up",
            timestamp=NOW,
            candle_index=index,
            severity="warning",
            source_rule="close_far_above_ema20_by_atr_multiple",
            source_indicators=("close", "ema_20", "atr_14"),
            reason="Close is extended above EMA 20.",
            price=Decimal("120"),
            invalidation_condition="Mean reversion back toward EMA 20.",
        )
        for index in range(10)
    )
    scores = score_technical_analysis(
        candle_count=120,
        trend_regime=RegimeClassification(
            regime="uptrend",
            source_rule="close_above_short_sma_above_long_sma",
            reason="Latest close is above aligned moving averages.",
        ),
        volatility_regime=RegimeClassification(
            regime="normal_volatility",
            source_rule="latest_atr_within_trailing_baseline_band",
            reason="Latest ATR is within its baseline band.",
        ),
        technical_events=warning_events,
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

    score_by_category = {score.category: score for score in scores}
    assert score_by_category["setup_quality"].score == Decimal("90")
    assert score_by_category["risk"].score == Decimal("40")
    assert score_by_category["data_quality"].score == Decimal("100")
    assert score_by_category["risk"].reasons[-1].code == "warning_technical_events"
