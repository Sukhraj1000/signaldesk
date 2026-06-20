from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from signaldesk_backend import (
    Candle,
    LevelZone,
    SwingPoint,
    Symbol,
    average_true_range,
    detect_support_resistance_zones,
    detect_swing_highs,
    detect_swing_lows,
    detect_swing_points,
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
        make_volume_candle(index, volume)
        for index, volume in enumerate((100, 200, 300, 600))
    )

    assert volume_moving_average(candles, period=3) == (
        None,
        None,
        Decimal("200"),
        Decimal("366.6666666666666666666666667"),
    )


def test_relative_volume_compares_volume_to_prior_trailing_average() -> None:
    candles = tuple(
        make_volume_candle(index, volume)
        for index, volume in enumerate((100, 200, 300, 600))
    )

    assert relative_volume(candles, period=3) == (
        None,
        None,
        None,
        Decimal("3"),
    )


def test_volume_indicators_return_warmup_values_for_insufficient_input() -> None:
    candles = tuple(
        make_volume_candle(index, volume) for index, volume in enumerate((100, 200))
    )

    assert volume_moving_average(candles, period=3) == (None, None)
    assert relative_volume(candles, period=3) == (None, None)


def test_relative_volume_returns_none_for_zero_trailing_average() -> None:
    candles = tuple(
        make_volume_candle(index, volume) for index, volume in enumerate((0, 0, 0, 100))
    )

    assert relative_volume(candles, period=3) == (None, None, None, None)


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
            tuple(
                make_volume_candle(index, int(value))
                for index, value in enumerate(values)
            ),
            period=0,
        ),
        lambda values: relative_volume(
            tuple(
                make_volume_candle(index, int(value))
                for index, value in enumerate(values)
            ),
            period=0,
        ),
        lambda values: average_true_range(
            tuple(
                make_candle(index, str(value)) for index, value in enumerate(values)
            ),
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
            tuple(
                make_volume_candle(index, int(value))
                for index, value in enumerate(values)
            ),
            period=3,
        ),
        lambda values: relative_volume(
            tuple(
                make_volume_candle(index, int(value))
                for index, value in enumerate(values)
            ),
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
