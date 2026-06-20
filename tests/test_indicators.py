from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from signaldesk_backend import (
    Candle,
    Symbol,
    average_true_range,
    exponential_moving_average,
    macd,
    relative_strength_index,
    simple_moving_average,
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


@pytest.mark.parametrize(
    "indicator",
    [
        lambda values: simple_moving_average(values, period=0),
        lambda values: exponential_moving_average(values, period=0),
        lambda values: relative_strength_index(values, period=0),
        lambda values: macd(values, fast_period=0),
        lambda values: macd(values, slow_period=0),
        lambda values: macd(values, signal_period=0),
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
