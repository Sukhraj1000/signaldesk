from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from signaldesk_backend import Candle, Symbol, exponential_moving_average, simple_moving_average

Indicator = Callable[[tuple[Decimal, ...]], tuple[Decimal | None, ...]]


SYMBOL = Symbol("AMD")
START = datetime(2026, 1, 1, tzinfo=UTC)


def make_candle(index: int, close: str) -> Candle:
    price = Decimal(close)
    return Candle(
        symbol=SYMBOL,
        timestamp=START + timedelta(days=index),
        open=price,
        high=price,
        low=price,
        close=price,
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


@pytest.mark.parametrize(
    "indicator",
    [
        lambda values: simple_moving_average(values, period=0),
        lambda values: exponential_moving_average(values, period=0),
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
    ],
)
def test_moving_averages_preserve_input_length_for_empty_and_insufficient_inputs(
    indicator: Indicator,
) -> None:
    assert indicator(()) == ()
    assert indicator((Decimal("10"), Decimal("11"))) == (None, None)
