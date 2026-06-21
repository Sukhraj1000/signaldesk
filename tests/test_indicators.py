from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from signaldesk_backend import (
    Candle,
    ConfirmationInvalidationLevel,
    ConfirmationInvalidationLevels,
    DeterministicTechnicalEvent,
    FibonacciRetracementLevel,
    LevelZone,
    SwingPoint,
    Symbol,
    average_true_range,
    calculate_fibonacci_retracement_levels,
    classify_trend_regime,
    classify_volatility_regime,
    classify_volume_regime,
    derive_confirmation_invalidation_levels,
    detect_breakout_breakdown_events,
    detect_moving_average_cross_events,
    detect_overextension_events,
    detect_relative_volume_spike_events,
    detect_support_resistance_zones,
    detect_swing_highs,
    detect_swing_lows,
    detect_swing_points,
    detect_volatility_regime_events,
    exponential_moving_average,
    macd,
    relative_strength_index,
    relative_volume,
    simple_moving_average,
    volume_moving_average,
)

Indicator = Callable[[tuple[Decimal, ...]], tuple[Decimal | None, ...]]


SYMBOL = Symbol("AMD")
START = datetime(2026, 1, 1, tzinfo=UTC)


def make_candle(index: int, close: str) -> Candle:
    price = Decimal(close)
    return make_ohlc_candle(index, open_=price, high=price, low=price, close=price)


def make_ohlc_candle(
    index: int, *, open_: Decimal, high: Decimal, low: Decimal, close: Decimal
) -> Candle:
    return Candle(
        symbol=SYMBOL,
        timestamp=START + timedelta(days=index),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000 + index,
    )


def make_volume_candle(index: int, volume: int) -> Candle:
    return Candle(
        symbol=SYMBOL,
        timestamp=START + timedelta(days=index),
        open=Decimal("10"),
        high=Decimal("10"),
        low=Decimal("10"),
        close=Decimal("10"),
        volume=volume,
    )


def test_simple_moving_average_returns_aligned_rolling_means_for_numeric_closes() -> None:
    values = (Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), Decimal("5"))

    assert simple_moving_average(values, period=3) == (
        None,
        None,
        Decimal("2"),
        Decimal("3"),
        Decimal("4"),
    )


def test_simple_moving_average_accepts_candles_and_uses_close_prices() -> None:
    candles = tuple(make_candle(index, close) for index, close in enumerate(("10", "11", "15")))

    assert simple_moving_average(candles, period=2) == (
        None,
        Decimal("10.5"),
        Decimal("13"),
    )


def test_exponential_moving_average_uses_sma_seed_then_standard_multiplier() -> None:
    values = (Decimal("10"), Decimal("11"), Decimal("12"), Decimal("13"), Decimal("14"))

    assert exponential_moving_average(values, period=3) == (
        None,
        None,
        Decimal("11"),
        Decimal("12.0"),
        Decimal("13.00"),
    )


def test_exponential_moving_average_accepts_candles_and_uses_close_prices() -> None:
    candles = tuple(make_candle(index, close) for index, close in enumerate(("10", "12", "14")))

    assert exponential_moving_average(candles, period=2) == (
        None,
        Decimal("11"),
        Decimal("13.00000000000000000000000000"),
    )


def test_relative_strength_index_uses_wilder_smoothing() -> None:
    values = tuple(
        Decimal(value)
        for value in (
            "44.34",
            "44.09",
            "44.15",
            "43.61",
            "44.33",
            "44.83",
            "45.10",
            "45.42",
            "45.84",
            "46.08",
            "45.89",
            "46.03",
            "45.61",
            "46.28",
            "46.28",
            "46.00",
        )
    )

    rsi = relative_strength_index(values, period=14)

    assert rsi[:14] == (None,) * 14
    assert rsi[14] == Decimal("70.46413502109704641350210971")
    assert rsi[15] == Decimal("66.24961855355508086664632285")


def test_relative_strength_index_accepts_candles_and_uses_close_prices() -> None:
    candles = tuple(make_candle(index, close) for index, close in enumerate(("10", "11", "12")))

    assert relative_strength_index(candles, period=2) == (
        None,
        None,
        Decimal("100"),
    )


def test_relative_strength_index_documents_flat_series_as_neutral() -> None:
    assert relative_strength_index((Decimal("10"), Decimal("10"), Decimal("10")), period=2) == (
        None,
        None,
        Decimal("50"),
    )


def test_macd_returns_aligned_line_signal_and_histogram() -> None:
    values = tuple(Decimal(value) for value in range(1, 11))

    result = macd(values, fast_period=3, slow_period=6, signal_period=3)

    assert result.macd_line == (
        None,
        None,
        None,
        None,
        None,
        Decimal("1.500"),
        Decimal("1.500000000000000000000000000"),
        Decimal("1.500000000000000000000000000"),
        Decimal("1.500000000000000000000000000"),
        Decimal("1.500000000000000000000000000"),
    )
    assert result.signal_line == (
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        Decimal("1.500000000000000000000000000"),
        Decimal("1.500000000000000000000000000"),
        Decimal("1.500000000000000000000000000"),
    )
    assert result.histogram == (
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        Decimal("0E-27"),
        Decimal("0E-27"),
        Decimal("0E-27"),
    )


def test_macd_accepts_candles_and_uses_close_prices() -> None:
    candles = tuple(make_candle(index, str(index + 1)) for index in range(10))

    result = macd(candles, fast_period=3, slow_period=6, signal_period=3)

    assert result.macd_line[-1] == Decimal("1.500000000000000000000000000")
    assert result.signal_line[-1] == Decimal("1.500000000000000000000000000")
    assert result.histogram[-1] == Decimal("0E-27")


def test_average_true_range_uses_previous_close_for_gap_true_range() -> None:
    candles = (
        make_ohlc_candle(
            0,
            open_=Decimal("9"),
            high=Decimal("10"),
            low=Decimal("8"),
            close=Decimal("10"),
        ),
        make_ohlc_candle(
            1,
            open_=Decimal("14"),
            high=Decimal("15"),
            low=Decimal("14"),
            close=Decimal("14.5"),
        ),
    )

    assert average_true_range(candles, period=1) == (Decimal("2"), Decimal("5"))


def test_average_true_range_returns_none_until_enough_candle_history() -> None:
    candles = tuple(make_candle(index, close) for index, close in enumerate(("10", "11")))

    assert average_true_range(candles, period=3) == (None, None)


def test_average_true_range_uses_sma_seed_then_wilder_smoothing() -> None:
    candles = (
        make_ohlc_candle(
            0,
            open_=Decimal("9"),
            high=Decimal("10"),
            low=Decimal("8"),
            close=Decimal("9"),
        ),
        make_ohlc_candle(
            1,
            open_=Decimal("11"),
            high=Decimal("12"),
            low=Decimal("9"),
            close=Decimal("11"),
        ),
        make_ohlc_candle(
            2,
            open_=Decimal("12"),
            high=Decimal("13"),
            low=Decimal("10"),
            close=Decimal("12"),
        ),
        make_ohlc_candle(
            3,
            open_=Decimal("13.25"),
            high=Decimal("14"),
            low=Decimal("13"),
            close=Decimal("13.5"),
        ),
    )

    assert average_true_range(candles, period=3) == (
        None,
        None,
        Decimal("2.666666666666666666666666667"),
        Decimal("2.444444444444444444444444445"),
    )


def test_volume_moving_average_returns_aligned_rolling_means() -> None:
    candles = tuple(
        make_volume_candle(index, volume) for index, volume in enumerate((100, 200, 300, 600))
    )

    assert volume_moving_average(candles, period=3) == (
        None,
        None,
        Decimal("200"),
        Decimal("366.6666666666666666666666667"),
    )


def test_relative_volume_compares_volume_to_prior_trailing_average() -> None:
    candles = tuple(
        make_volume_candle(index, volume) for index, volume in enumerate((100, 200, 300, 600))
    )

    assert relative_volume(candles, period=3) == (
        None,
        None,
        None,
        Decimal("3"),
    )


def test_volume_indicators_return_warmup_values_for_insufficient_input() -> None:
    candles = tuple(make_volume_candle(index, volume) for index, volume in enumerate((100, 200)))

    assert volume_moving_average(candles, period=3) == (None, None)
    assert relative_volume(candles, period=3) == (None, None)


def test_relative_volume_returns_none_for_zero_trailing_average() -> None:
    candles = tuple(
        make_volume_candle(index, volume) for index, volume in enumerate((0, 0, 0, 100))
    )

    assert relative_volume(candles, period=3) == (None, None, None, None)


def test_classify_trend_regime_uses_moving_average_alignment() -> None:
    uptrend = tuple(Decimal(index) for index in range(1, 61))
    downtrend = tuple(Decimal(index) for index in range(60, 0, -1))
    sideways = (Decimal("10"),) * 60

    assert classify_trend_regime(uptrend, short_period=3, long_period=5).regime == "uptrend"
    assert classify_trend_regime(downtrend, short_period=3, long_period=5).regime == "downtrend"
    assert classify_trend_regime(sideways, short_period=3, long_period=5).regime == "sideways"


def test_classify_trend_regime_reports_insufficient_history() -> None:
    result = classify_trend_regime((Decimal("10"), Decimal("11")), short_period=2, long_period=3)

    assert result.regime == "unknown"
    assert result.source_rule == "insufficient_history_for_trend_regime"


def test_classify_volatility_regime_compares_atr_to_historical_baseline() -> None:
    compressed = tuple(make_candle(index, "10") for index in range(9))
    normal = tuple(
        make_ohlc_candle(
            index,
            open_=Decimal("10"),
            high=Decimal("11"),
            low=Decimal("9"),
            close=Decimal("10"),
        )
        for index in range(9)
    )
    expanded = (
        *normal[:-1],
        make_ohlc_candle(
            8,
            open_=Decimal("10"),
            high=Decimal("20"),
            low=Decimal("5"),
            close=Decimal("10"),
        ),
    )

    assert (
        classify_volatility_regime(compressed, atr_period=3, baseline_period=6).regime
        == "volatility_compression"
    )
    assert (
        classify_volatility_regime(normal, atr_period=3, baseline_period=6).regime
        == "normal_volatility"
    )
    assert (
        classify_volatility_regime(expanded, atr_period=3, baseline_period=6).regime
        == "volatility_expansion"
    )


def test_classify_volatility_regime_detects_positive_atr_after_zero_baseline() -> None:
    candles = (
        *(make_candle(index, "10") for index in range(5)),
        make_ohlc_candle(
            5,
            open_=Decimal("10"),
            high=Decimal("15"),
            low=Decimal("5"),
            close=Decimal("10"),
        ),
    )

    result = classify_volatility_regime(candles, atr_period=3, baseline_period=3)

    assert result.regime == "volatility_expansion"
    assert result.source_rule == "positive_latest_atr_against_zero_atr_baseline"


def test_classify_volatility_regime_reports_insufficient_history() -> None:
    result = classify_volatility_regime(
        tuple(make_candle(index, "10") for index in range(4)),
        atr_period=3,
        baseline_period=3,
    )

    assert result.regime == "unknown"
    assert result.source_rule == "insufficient_history_for_volatility_regime"


def test_classify_volume_regime_uses_prior_trailing_average() -> None:
    high_volume = tuple(
        make_volume_candle(index, volume) for index, volume in enumerate((100, 100, 100, 200))
    )
    low_volume = tuple(
        make_volume_candle(index, volume) for index, volume in enumerate((100, 100, 100, 50))
    )
    normal_volume = tuple(
        make_volume_candle(index, volume) for index, volume in enumerate((100, 100, 100, 100))
    )

    assert classify_volume_regime(high_volume, period=3).regime == "high_volume"
    assert classify_volume_regime(low_volume, period=3).regime == "low_volume"
    assert classify_volume_regime(normal_volume, period=3).regime == "normal_volume"


def test_classify_volume_regime_reports_unavailable_zero_baseline() -> None:
    result = classify_volume_regime(
        tuple(make_volume_candle(index, volume) for index, volume in enumerate((0, 0, 0, 100))),
        period=3,
    )

    assert result.regime == "unknown"
    assert result.source_rule == "unavailable_relative_volume_for_volume_regime"


def test_calculate_fibonacci_retracement_levels_for_upward_move() -> None:
    assert calculate_fibonacci_retracement_levels(Decimal("100"), Decimal("200")) == (
        FibonacciRetracementLevel(
            ratio=Decimal("0.236"),
            percent=Decimal("23.6"),
            price=Decimal("176.400"),
            direction="up",
            swing_start=Decimal("100"),
            swing_end=Decimal("200"),
        ),
        FibonacciRetracementLevel(
            ratio=Decimal("0.382"),
            percent=Decimal("38.2"),
            price=Decimal("161.800"),
            direction="up",
            swing_start=Decimal("100"),
            swing_end=Decimal("200"),
        ),
        FibonacciRetracementLevel(
            ratio=Decimal("0.5"),
            percent=Decimal("50.0"),
            price=Decimal("150.0"),
            direction="up",
            swing_start=Decimal("100"),
            swing_end=Decimal("200"),
        ),
        FibonacciRetracementLevel(
            ratio=Decimal("0.618"),
            percent=Decimal("61.8"),
            price=Decimal("138.200"),
            direction="up",
            swing_start=Decimal("100"),
            swing_end=Decimal("200"),
        ),
        FibonacciRetracementLevel(
            ratio=Decimal("0.786"),
            percent=Decimal("78.6"),
            price=Decimal("121.400"),
            direction="up",
            swing_start=Decimal("100"),
            swing_end=Decimal("200"),
        ),
    )


def test_calculate_fibonacci_retracement_levels_for_downward_move() -> None:
    levels = calculate_fibonacci_retracement_levels("200", "100")

    assert tuple(level.price for level in levels) == (
        Decimal("123.600"),
        Decimal("138.200"),
        Decimal("150.0"),
        Decimal("161.800"),
        Decimal("178.600"),
    )
    assert {level.direction for level in levels} == {"down"}
    assert all(level.swing_start == Decimal("200") for level in levels)
    assert all(level.swing_end == Decimal("100") for level in levels)


def test_calculate_fibonacci_retracement_levels_rejects_zero_width_range() -> None:
    with pytest.raises(ValueError, match="swing range must not be zero-width"):
        calculate_fibonacci_retracement_levels(Decimal("100"), Decimal("100"))


def test_detect_swing_highs_returns_structured_local_maxima() -> None:
    candles = tuple(
        make_ohlc_candle(
            index,
            open_=Decimal("10"),
            high=Decimal(str(high)),
            low=Decimal("9"),
            close=Decimal("10"),
        )
        for index, high in enumerate((10, 12, 15, 11, 13, 10, 14))
    )

    assert detect_swing_highs(candles, window=1) == (
        SwingPoint(
            kind="high",
            candle_index=2,
            timestamp=candles[2].timestamp,
            price=Decimal("15"),
            candle=candles[2],
        ),
        SwingPoint(
            kind="high",
            candle_index=4,
            timestamp=candles[4].timestamp,
            price=Decimal("13"),
            candle=candles[4],
        ),
    )


def test_detect_swing_lows_returns_structured_local_minima() -> None:
    candles = tuple(
        make_ohlc_candle(
            index,
            open_=Decimal("10"),
            high=Decimal("12"),
            low=Decimal(str(low)),
            close=Decimal("10"),
        )
        for index, low in enumerate((8, 7, 6, 7, 5, 8, 4))
    )

    assert detect_swing_lows(candles, window=1) == (
        SwingPoint(
            kind="low",
            candle_index=2,
            timestamp=candles[2].timestamp,
            price=Decimal("6"),
            candle=candles[2],
        ),
        SwingPoint(
            kind="low",
            candle_index=4,
            timestamp=candles[4].timestamp,
            price=Decimal("5"),
            candle=candles[4],
        ),
    )


def test_detect_swing_points_combines_highs_and_lows_by_candle_order() -> None:
    candles = tuple(
        make_ohlc_candle(
            index,
            open_=Decimal("10"),
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            close=Decimal("10"),
        )
        for index, high, low in (
            (0, 10, 8),
            (1, 14, 7),
            (2, 11, 6),
            (3, 16, 9),
            (4, 12, 5),
            (5, 13, 8),
        )
    )

    points = detect_swing_points(candles, window=1)

    assert tuple(point.kind for point in points) == ("high", "low", "high", "low")
    assert tuple(point.candle_index for point in points) == (1, 2, 3, 4)
    assert tuple(point.price for point in points) == (
        Decimal("14"),
        Decimal("6"),
        Decimal("16"),
        Decimal("5"),
    )


def test_swing_detection_excludes_edges_and_requires_full_window() -> None:
    candles = tuple(
        make_ohlc_candle(
            index,
            open_=Decimal("10"),
            high=Decimal(str(high)),
            low=Decimal("9"),
            close=Decimal("10"),
        )
        for index, high in enumerate((20, 10, 11, 12, 30))
    )

    assert detect_swing_highs(candles, window=1) == ()
    assert detect_swing_highs(candles[:2], window=1) == ()


def test_swing_detection_supports_asymmetric_lookback_and_lookahead() -> None:
    candles = tuple(
        make_ohlc_candle(
            index,
            open_=Decimal("10"),
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            close=Decimal("10"),
        )
        for index, high, low in (
            (0, 10, 8),
            (1, 11, 7),
            (2, 15, 6),
            (3, 12, 8),
            (4, 16, 7),
            (5, 13, 9),
        )
    )

    assert detect_swing_highs(candles, lookback=2, lookahead=1) == (
        SwingPoint(
            kind="high",
            candle_index=2,
            timestamp=candles[2].timestamp,
            price=Decimal("15"),
            candle=candles[2],
        ),
        SwingPoint(
            kind="high",
            candle_index=4,
            timestamp=candles[4].timestamp,
            price=Decimal("16"),
            candle=candles[4],
        ),
    )
    assert detect_swing_lows(candles, lookback=1, lookahead=2) == (
        SwingPoint(
            kind="low",
            candle_index=2,
            timestamp=candles[2].timestamp,
            price=Decimal("6"),
            candle=candles[2],
        ),
    )


def test_swing_detection_uses_strict_comparison_for_ties() -> None:
    candles = tuple(
        make_ohlc_candle(
            index,
            open_=Decimal("10"),
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            close=Decimal("10"),
        )
        for index, high, low in (
            (0, 10, 8),
            (1, 12, 7),
            (2, 12, 7),
            (3, 11, 8),
        )
    )

    assert detect_swing_highs(candles, window=1) == ()
    assert detect_swing_lows(candles, window=1) == ()


def test_swing_detection_rejects_non_positive_windows() -> None:
    with pytest.raises(ValueError, match="lookback must be positive"):
        detect_swing_points((make_candle(0, "10"),), window=0)
    with pytest.raises(ValueError, match="lookahead must be positive"):
        detect_swing_points((make_candle(0, "10"),), lookahead=0)


def test_detect_support_resistance_zones_clusters_nearby_swing_levels() -> None:
    candles = tuple(
        make_ohlc_candle(
            index,
            open_=Decimal("10"),
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            close=Decimal("10"),
        )
        for index, high, low in (
            (0, 10, 8),
            (1, 15, 7),
            (2, 11, 9),
            (3, 15.2, 6.8),
            (4, 12, 9),
            (5, 20, 6.9),
            (6, 13, 8),
        )
    )

    result = detect_support_resistance_zones(
        candles,
        window=1,
        tolerance=Decimal("0.30"),
        tolerance_mode="absolute",
    )

    assert result.resistance[0] == LevelZone(
        kind="resistance",
        lower_bound=Decimal("15"),
        upper_bound=Decimal("15.2"),
        representative_price=Decimal("15.1"),
        evidence_count=2,
        first_candle_index=1,
        last_candle_index=3,
        touches=(
            detect_swing_points(candles, window=1)[0],
            detect_swing_points(candles, window=1)[2],
        ),
    )
    assert result.support[0].lower_bound == Decimal("6.8")
    assert result.support[0].upper_bound == Decimal("7")
    assert result.support[0].representative_price == Decimal("6.9")
    assert result.support[0].evidence_count == 3


def test_detect_support_resistance_zones_separates_support_from_resistance() -> None:
    candles = tuple(
        make_ohlc_candle(
            index,
            open_=Decimal("10"),
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            close=Decimal("10"),
        )
        for index, high, low in (
            (0, 10, 8),
            (1, 14, 7),
            (2, 11, 9),
            (3, 14.1, 6.9),
            (4, 12, 9),
        )
    )

    result = detect_support_resistance_zones(
        candles,
        window=1,
        tolerance=Decimal("0.2"),
        tolerance_mode="absolute",
    )

    assert tuple(zone.kind for zone in result.support) == ("support",)
    assert tuple(zone.kind for zone in result.resistance) == ("resistance",)
    assert result.support[0].representative_price == Decimal("6.95")
    assert result.resistance[0].representative_price == Decimal("14.05")


def test_detect_support_resistance_zones_accepts_precomputed_swing_points() -> None:
    candles = tuple(make_candle(index, "10") for index in range(4))
    swing_points = (
        SwingPoint("high", 0, candles[0].timestamp, Decimal("12"), candles[0]),
        SwingPoint("high", 1, candles[1].timestamp, Decimal("12.05"), candles[1]),
        SwingPoint("low", 2, candles[2].timestamp, Decimal("9"), candles[2]),
    )

    result = detect_support_resistance_zones(
        swing_points=swing_points,
        tolerance=Decimal("0.1"),
        tolerance_mode="absolute",
    )

    assert len(result.resistance) == 1
    assert result.resistance[0].evidence_count == 2
    assert len(result.support) == 1


def test_detect_support_resistance_zones_returns_empty_result_for_insufficient_input() -> None:
    assert detect_support_resistance_zones((), window=1).support == ()
    assert detect_support_resistance_zones((), window=1).resistance == ()
    assert detect_support_resistance_zones(swing_points=()).support == ()
    assert detect_support_resistance_zones(swing_points=()).resistance == ()


def test_derive_confirmation_invalidation_levels_from_nearest_zones() -> None:
    candles = tuple(
        make_ohlc_candle(
            index,
            open_=Decimal("10"),
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            close=Decimal(str(close)),
        )
        for index, high, low, close in (
            (0, "10", "8.50", "9"),
            (1, "12.05", "9", "12"),
            (2, "11", "8", "8.50"),
            (3, "12", "9", "11"),
            (4, "10", "8.05", "9"),
            (5, "11", "9", "10"),
        )
    )

    levels = derive_confirmation_invalidation_levels(candles, window=1)

    assert levels.confirmation is not None
    assert levels.confirmation.kind == "confirmation"
    assert levels.confirmation.price == Decimal("12.025")
    assert levels.confirmation.source_rule == "nearest_resistance_above_latest_close"
    assert levels.confirmation.source_level == "resistance_zone[12,12.05] touches=2"
    assert "confirm" in levels.confirmation.reason
    assert levels.invalidation is not None
    assert levels.invalidation.kind == "invalidation"
    assert levels.invalidation.price == Decimal("8.025")
    assert levels.invalidation.source_rule == "nearest_support_below_latest_close"
    assert levels.invalidation.source_level == "support_zone[8,8.05] touches=2"
    assert "invalidate" in levels.invalidation.reason


def test_derive_confirmation_invalidation_levels_reports_unavailable_sides_as_none() -> None:
    candles = tuple(make_candle(index, "10") for index in range(5))

    levels = derive_confirmation_invalidation_levels(candles, window=1)

    assert levels.confirmation is None
    assert levels.invalidation is None


def test_detect_moving_average_cross_events_reports_reclaims_and_losses() -> None:
    reclaimed = tuple(
        make_candle(index, close)
        for index, close in enumerate(("10", "10", "10", "9", "12"))
    )
    lost = tuple(
        make_candle(index, close)
        for index, close in enumerate(("10", "10", "10", "11", "8"))
    )

    reclaim_events = detect_moving_average_cross_events(reclaimed, period=3)
    lost_events = detect_moving_average_cross_events(lost, period=3)

    assert reclaim_events == (
        DeterministicTechnicalEvent(
            event_type="reclaimed_moving_average",
            timestamp=reclaimed[-1].timestamp,
            candle_index=4,
            severity="bullish",
            source_rule="close_crossed_above_sma",
            source_indicators=("sma_3",),
            reason=(
                "Latest close 12 moved above sma_3 10.33333333333333333333333333 "
                "after the prior close was not above its SMA."
            ),
            price=Decimal("12"),
            invalidation_condition=(
                "A close back below sma_3 10.33333333333333333333333333 would "
                "invalidate the reclaim event."
            ),
        ),
    )
    assert lost_events == (
        DeterministicTechnicalEvent(
            event_type="lost_moving_average",
            timestamp=lost[-1].timestamp,
            candle_index=4,
            severity="bearish",
            source_rule="close_crossed_below_sma",
            source_indicators=("sma_3",),
            reason=(
                "Latest close 8 moved below sma_3 9.666666666666666666666666667 "
                "after the prior close was not below its SMA."
            ),
            price=Decimal("8"),
            invalidation_condition=(
                "A close back above sma_3 9.666666666666666666666666667 would "
                "invalidate the loss event."
            ),
        ),
    )


def test_detect_moving_average_cross_events_returns_empty_without_cross_or_history() -> None:
    no_cross = tuple(
        make_candle(index, close)
        for index, close in enumerate(("10", "10", "10", "11", "12"))
    )

    assert detect_moving_average_cross_events(no_cross, period=3) == ()
    assert detect_moving_average_cross_events(no_cross[:3], period=3) == ()


def test_detect_breakout_breakdown_events_reports_level_crosses() -> None:
    breakout_candles = tuple(
        make_candle(index, close) for index, close in enumerate(("10", "10.50", "12"))
    )
    breakdown_candles = tuple(
        make_candle(index, close) for index, close in enumerate(("10", "9.50", "8"))
    )
    levels = ConfirmationInvalidationLevels(
        confirmation=ConfirmationInvalidationLevel(
            kind="confirmation",
            price=Decimal("11"),
            source_rule="nearest_resistance_above_latest_close",
            source_level="resistance_zone[10.8,11.2] touches=2",
            reason="fixture confirmation level",
        ),
        invalidation=ConfirmationInvalidationLevel(
            kind="invalidation",
            price=Decimal("9"),
            source_rule="nearest_support_below_latest_close",
            source_level="support_zone[8.8,9.2] touches=2",
            reason="fixture invalidation level",
        ),
    )

    assert detect_breakout_breakdown_events(breakout_candles, levels=levels) == (
        DeterministicTechnicalEvent(
            event_type="breakout",
            timestamp=breakout_candles[-1].timestamp,
            candle_index=2,
            severity="bullish",
            source_rule="latest_close_crossed_above_confirmation_level",
            source_indicators=("resistance_zone[10.8,11.2] touches=2",),
            reason=(
                "Latest close 12 crossed above confirmation level 11 from "
                "resistance_zone[10.8,11.2] touches=2."
            ),
            price=Decimal("12"),
            invalidation_condition=(
                "A close back below confirmation level 11 would invalidate the breakout event."
            ),
        ),
    )
    assert detect_breakout_breakdown_events(breakdown_candles, levels=levels) == (
        DeterministicTechnicalEvent(
            event_type="breakdown",
            timestamp=breakdown_candles[-1].timestamp,
            candle_index=2,
            severity="bearish",
            source_rule="latest_close_crossed_below_invalidation_level",
            source_indicators=("support_zone[8.8,9.2] touches=2",),
            reason=(
                "Latest close 8 crossed below invalidation level 9 from "
                "support_zone[8.8,9.2] touches=2."
            ),
            price=Decimal("8"),
            invalidation_condition=(
                "A close back above invalidation level 9 would invalidate the breakdown event."
            ),
        ),
    )


def test_detect_breakout_breakdown_events_derives_prior_setup_levels() -> None:
    prior_candles = tuple(
        make_ohlc_candle(
            index,
            open_=Decimal("10"),
            high=Decimal(str(high)),
            low=Decimal(str(low)),
            close=Decimal(str(close)),
        )
        for index, high, low, close in (
            (0, "10", "8.50", "9"),
            (1, "12.05", "9", "12"),
            (2, "11", "8", "8.50"),
            (3, "12", "9", "11"),
            (4, "10", "8.05", "9"),
            (5, "11", "9", "10"),
        )
    )
    breakout_candles = (
        *prior_candles,
        make_ohlc_candle(
            6,
            open_=Decimal("10"),
            high=Decimal("13.50"),
            low=Decimal("9.75"),
            close=Decimal("13"),
        ),
    )
    breakdown_candles = (
        *prior_candles,
        make_ohlc_candle(
            6,
            open_=Decimal("10"),
            high=Decimal("10.25"),
            low=Decimal("6.75"),
            close=Decimal("7"),
        ),
    )

    breakout_events = detect_breakout_breakdown_events(breakout_candles, window=1)
    breakdown_events = detect_breakout_breakdown_events(breakdown_candles, window=1)

    assert tuple(event.event_type for event in breakout_events) == ("breakout",)
    assert breakout_events[0].source_rule == "latest_close_crossed_above_confirmation_level"
    assert breakout_events[0].source_indicators == ("resistance_zone[12,12.05] touches=2",)
    assert "confirmation level 12.025" in breakout_events[0].reason
    assert tuple(event.event_type for event in breakdown_events) == ("breakdown",)
    assert breakdown_events[0].source_rule == "latest_close_crossed_below_invalidation_level"
    assert breakdown_events[0].source_indicators == ("support_zone[8,8.05] touches=2",)
    assert "invalidation level 8.025" in breakdown_events[0].reason


def test_detect_breakout_breakdown_events_returns_empty_without_cross_or_levels() -> None:
    no_cross = tuple(
        make_candle(index, close) for index, close in enumerate(("10", "10.50", "10.75"))
    )
    levels = ConfirmationInvalidationLevels(
        confirmation=ConfirmationInvalidationLevel(
            kind="confirmation",
            price=Decimal("11"),
            source_rule="nearest_resistance_above_latest_close",
            source_level="resistance_zone[11,11] touches=1",
            reason="fixture confirmation level",
        ),
        invalidation=None,
    )

    assert detect_breakout_breakdown_events(no_cross, levels=levels) == ()
    assert detect_breakout_breakdown_events(no_cross[:1], levels=levels) == ()
    assert detect_breakout_breakdown_events(no_cross) == ()


def test_detect_relative_volume_spike_events_reports_traceable_spike() -> None:
    candles = tuple(
        make_volume_candle(index, volume) for index, volume in enumerate((100, 100, 100, 200))
    )

    assert detect_relative_volume_spike_events(candles, period=3) == (
        DeterministicTechnicalEvent(
            event_type="relative_volume_spike",
            timestamp=candles[-1].timestamp,
            candle_index=3,
            severity="info",
            source_rule="latest_volume_at_least_threshold_x_prior_average",
            source_indicators=("relative_volume_3",),
            reason="Latest volume 200 is 2x its prior 3-candle average volume 100.",
            price=Decimal("10"),
            invalidation_condition=(
                "Relative volume below 1.5x the prior 3-candle average would end "
                "the spike condition."
            ),
        ),
    )


def test_detect_relative_volume_spike_events_returns_empty_without_spike_or_baseline() -> None:
    normal_volume = tuple(
        make_volume_candle(index, volume) for index, volume in enumerate((100, 100, 100, 120))
    )
    zero_baseline = tuple(
        make_volume_candle(index, volume) for index, volume in enumerate((0, 0, 0, 200))
    )

    assert detect_relative_volume_spike_events(normal_volume, period=3) == ()
    assert detect_relative_volume_spike_events(normal_volume[:3], period=3) == ()
    assert detect_relative_volume_spike_events(zero_baseline, period=3) == ()


def test_detect_relative_volume_spike_events_rejects_non_positive_threshold() -> None:
    with pytest.raises(ValueError, match="threshold must be positive"):
        detect_relative_volume_spike_events((make_volume_candle(0, 100),), threshold=Decimal("0"))


def test_detect_overextension_events_reports_traceable_upside_and_downside_events() -> None:
    upside = tuple(
        make_candle(index, close)
        for index, close in enumerate((*('10' for _ in range(18)), '14', '15'))
    )
    downside = tuple(
        make_candle(index, close)
        for index, close in enumerate((*('10' for _ in range(18)), '6', '5'))
    )

    assert detect_overextension_events(upside, ma_period=20, atr_period=14) == (
        DeterministicTechnicalEvent(
            event_type="overextension_up",
            timestamp=upside[-1].timestamp,
            candle_index=19,
            severity="warning",
            source_rule="latest_close_at_least_atr_multiple_above_sma",
            source_indicators=("sma_20", "atr_14"),
            reason=(
                "Latest close 15 is at least 2x ATR above sma_20 10.45; "
                "latest ATR is 0.3367346938775510204081632653."
            ),
            price=Decimal("15"),
            invalidation_condition=(
                "A close back within 2x ATR of sma_20 10.45 would end the upside "
                "overextension condition."
            ),
        ),
    )
    assert detect_overextension_events(downside, ma_period=20, atr_period=14) == (
        DeterministicTechnicalEvent(
            event_type="overextension_down",
            timestamp=downside[-1].timestamp,
            candle_index=19,
            severity="warning",
            source_rule="latest_close_at_least_atr_multiple_below_sma",
            source_indicators=("sma_20", "atr_14"),
            reason=(
                "Latest close 5 is at least 2x ATR below sma_20 9.55; "
                "latest ATR is 0.3367346938775510204081632653."
            ),
            price=Decimal("5"),
            invalidation_condition=(
                "A close back within 2x ATR of sma_20 9.55 would end the downside "
                "overextension condition."
            ),
        ),
    )


def test_detect_overextension_events_returns_empty_without_extension_or_history() -> None:
    normal = tuple(make_candle(index, "10") for index in range(20))

    assert detect_overextension_events(normal, ma_period=20, atr_period=14) == ()
    assert detect_overextension_events(normal[:19], ma_period=20, atr_period=14) == ()


def test_detect_overextension_events_rejects_non_positive_atr_multiple() -> None:
    with pytest.raises(ValueError, match="atr_multiple must be positive"):
        detect_overextension_events((make_candle(0, "10"),), atr_multiple=Decimal("0"))


def test_detect_volatility_regime_events_reports_expansion_and_compression() -> None:
    normal_range = tuple(
        make_ohlc_candle(
            index,
            open_=Decimal("10"),
            high=Decimal("11"),
            low=Decimal("9"),
            close=Decimal("10"),
        )
        for index in range(6)
    )
    expanded = (
        *normal_range[:-1],
        make_ohlc_candle(
            5,
            open_=Decimal("10"),
            high=Decimal("15"),
            low=Decimal("5"),
            close=Decimal("10"),
        ),
    )
    wide_range = tuple(
        make_ohlc_candle(
            index,
            open_=Decimal("10"),
            high=Decimal("13"),
            low=Decimal("7"),
            close=Decimal("10"),
        )
        for index in range(5)
    )
    compressed = (*wide_range, make_candle(5, "10"))

    assert detect_volatility_regime_events(expanded, atr_period=3, baseline_period=3) == (
        DeterministicTechnicalEvent(
            event_type="volatility_expansion",
            timestamp=expanded[-1].timestamp,
            candle_index=5,
            severity="warning",
            source_rule="latest_atr_at_least_threshold_x_trailing_baseline",
            source_indicators=("atr_3",),
            reason=(
                "Latest ATR 4.666666666666666666666666667 is "
                "2.333333333333333333333333334x its trailing 3-ATR baseline 2."
            ),
            price=Decimal("10"),
            invalidation_condition=(
                "ATR below 1.5x the trailing 3-ATR baseline would end the expansion "
                "condition."
            ),
        ),
    )
    assert detect_volatility_regime_events(compressed, atr_period=3, baseline_period=3) == (
        DeterministicTechnicalEvent(
            event_type="volatility_compression",
            timestamp=compressed[-1].timestamp,
            candle_index=5,
            severity="info",
            source_rule="latest_atr_at_most_threshold_x_trailing_baseline",
            source_indicators=("atr_3",),
            reason=(
                "Latest ATR 4 is 0.6666666666666666666666666667x its trailing "
                "3-ATR baseline 6."
            ),
            price=Decimal("10"),
            invalidation_condition=(
                "ATR above 0.75x the trailing 3-ATR baseline would end the compression "
                "condition."
            ),
        ),
    )


def test_detect_volatility_regime_events_returns_empty_without_event_or_history() -> None:
    normal = tuple(
        make_ohlc_candle(
            index,
            open_=Decimal("10"),
            high=Decimal("11"),
            low=Decimal("9"),
            close=Decimal("10"),
        )
        for index in range(6)
    )

    assert detect_volatility_regime_events(normal, atr_period=3, baseline_period=3) == ()
    assert detect_volatility_regime_events(normal[:5], atr_period=3, baseline_period=3) == ()


def test_detect_volatility_regime_events_rejects_invalid_thresholds() -> None:
    candles = (make_candle(0, "10"),)

    with pytest.raises(ValueError, match="volatility thresholds must be positive"):
        detect_volatility_regime_events(candles, expansion_threshold=Decimal("0"))
    with pytest.raises(
        ValueError, match="compression_threshold must be less than expansion_threshold"
    ):
        detect_volatility_regime_events(
            candles,
            expansion_threshold=Decimal("1.5"),
            compression_threshold=Decimal("1.5"),
        )


@pytest.mark.parametrize(
    "indicator",
    [
        lambda values: simple_moving_average(values, period=0),
        lambda values: exponential_moving_average(values, period=0),
        lambda values: relative_strength_index(values, period=0),
        lambda values: macd(values, fast_period=0),
        lambda values: macd(values, slow_period=0),
        lambda values: macd(values, signal_period=0),
        lambda values: volume_moving_average(
            tuple(make_volume_candle(index, int(value)) for index, value in enumerate(values)),
            period=0,
        ),
        lambda values: relative_volume(
            tuple(make_volume_candle(index, int(value)) for index, value in enumerate(values)),
            period=0,
        ),
        lambda values: average_true_range(
            tuple(make_candle(index, str(value)) for index, value in enumerate(values)),
            period=0,
        ),
    ],
)
def test_moving_averages_reject_non_positive_periods(indicator: Indicator) -> None:
    with pytest.raises(ValueError, match="period must be positive"):
        indicator((Decimal("1"),))


@pytest.mark.parametrize(
    "indicator",
    [
        lambda values: simple_moving_average(values, period=3),
        lambda values: exponential_moving_average(values, period=3),
        lambda values: relative_strength_index(values, period=3),
        lambda values: macd(values, fast_period=2, slow_period=3, signal_period=2).macd_line,
        lambda values: volume_moving_average(
            tuple(make_volume_candle(index, int(value)) for index, value in enumerate(values)),
            period=3,
        ),
        lambda values: relative_volume(
            tuple(make_volume_candle(index, int(value)) for index, value in enumerate(values)),
            period=3,
        ),
    ],
)
def test_moving_averages_preserve_input_length_for_empty_and_insufficient_inputs(
    indicator: Indicator,
) -> None:
    assert indicator(()) == ()
    assert indicator((Decimal("10"), Decimal("11"))) == (None, None)


def test_macd_rejects_fast_period_that_is_not_less_than_slow_period() -> None:
    with pytest.raises(ValueError, match="fast_period must be less than slow_period"):
        macd((Decimal("1"),), fast_period=6, slow_period=6)
