"""Deterministic technical-analysis indicator calculations."""

from collections.abc import Sequence
from decimal import Decimal

from signaldesk_backend.models import Candle

PriceInput = Candle | Decimal | int | float | str


def simple_moving_average(
    values: Sequence[PriceInput], *, period: int
) -> tuple[Decimal | None, ...]:
    """Return an input-aligned simple moving average over close prices.

    The result has the same length as ``values``. Entries are ``None`` until a
    complete rolling window is available, then the arithmetic mean of the most
    recent ``period`` prices is returned.
    """

    closes = _coerce_prices(values)
    _validate_period(period)
    if not closes:
        return ()

    averages: list[Decimal | None] = []
    rolling_sum = Decimal("0")
    decimal_period = Decimal(period)
    for index, close in enumerate(closes):
        rolling_sum += close
        if index >= period:
            rolling_sum -= closes[index - period]
        if index < period - 1:
            averages.append(None)
        else:
            averages.append(rolling_sum / decimal_period)
    return tuple(averages)


def exponential_moving_average(
    values: Sequence[PriceInput], *, period: int
) -> tuple[Decimal | None, ...]:
    """Return an input-aligned exponential moving average over close prices.

    This uses the standard multiplier ``2 / (period + 1)``. The first computable
    EMA value is seeded with the SMA of the initial complete window so callers
    can align indicator values with the original candle series.
    """

    closes = _coerce_prices(values)
    _validate_period(period)
    if not closes:
        return ()

    averages: list[Decimal | None] = [None] * min(period - 1, len(closes))
    if len(closes) < period:
        return tuple(averages)

    decimal_period = Decimal(period)
    multiplier = Decimal("2") / Decimal(period + 1)
    previous_ema = sum(closes[:period], Decimal("0")) / decimal_period
    averages.append(previous_ema)

    for close in closes[period:]:
        previous_ema = (close - previous_ema) * multiplier + previous_ema
        averages.append(previous_ema)
    return tuple(averages)


def _validate_period(period: int) -> None:
    if period <= 0:
        raise ValueError("period must be positive")


def _coerce_prices(values: Sequence[PriceInput]) -> tuple[Decimal, ...]:
    return tuple(_coerce_price(value) for value in values)


def _coerce_price(value: PriceInput) -> Decimal:
    if isinstance(value, Candle):
        return value.close
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
