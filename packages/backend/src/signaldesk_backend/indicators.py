"""Deterministic technical-analysis indicator calculations."""

from collections.abc import Sequence
from decimal import Decimal
from typing import NamedTuple

from signaldesk_backend.models import Candle

PriceInput = Candle | Decimal | int | float | str
CandleInput = Candle


class MacdResult(NamedTuple):
    """Input-aligned MACD indicator series."""

    macd_line: tuple[Decimal | None, ...]
    signal_line: tuple[Decimal | None, ...]
    histogram: tuple[Decimal | None, ...]


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


def relative_strength_index(
    values: Sequence[PriceInput], *, period: int = 14
) -> tuple[Decimal | None, ...]:
    """Return an input-aligned Relative Strength Index over close prices.

    RSI needs ``period`` price changes, so the first computable value appears at
    index ``period``. Initial average gain/loss values use simple means, then
    subsequent values use Wilder smoothing. A flat window with no gain or loss
    returns neutral RSI ``50``; a no-loss rising window returns ``100``.
    """

    closes = _coerce_prices(values)
    _validate_period(period)
    if not closes:
        return ()

    rsi_values: list[Decimal | None] = [None] * min(period, len(closes))
    if len(closes) <= period:
        return tuple(rsi_values)

    decimal_period = Decimal(period)
    gains: list[Decimal] = []
    losses: list[Decimal] = []
    for previous, current in zip(closes, closes[1:], strict=False):
        change = current - previous
        gains.append(max(change, Decimal("0")))
        losses.append(max(-change, Decimal("0")))

    average_gain = sum(gains[:period], Decimal("0")) / decimal_period
    average_loss = sum(losses[:period], Decimal("0")) / decimal_period
    rsi_values.append(_rsi_from_average_gain_loss(average_gain, average_loss))

    for gain, loss in zip(gains[period:], losses[period:], strict=True):
        average_gain = ((average_gain * Decimal(period - 1)) + gain) / decimal_period
        average_loss = ((average_loss * Decimal(period - 1)) + loss) / decimal_period
        rsi_values.append(_rsi_from_average_gain_loss(average_gain, average_loss))

    return tuple(rsi_values)


def macd(
    values: Sequence[PriceInput],
    *,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> MacdResult:
    """Return input-aligned MACD line, signal line, and histogram series.

    MACD is calculated as ``EMA(fast_period) - EMA(slow_period)`` over close
    prices. The signal line is an EMA of the computable MACD values, aligned
    back to the original input. The histogram is ``MACD - signal``. Entries that
    do not yet have enough source values are ``None``.
    """

    _validate_macd_periods(fast_period, slow_period, signal_period)

    fast_ema = exponential_moving_average(values, period=fast_period)
    slow_ema = exponential_moving_average(values, period=slow_period)
    macd_line = tuple(
        None if fast_value is None or slow_value is None else fast_value - slow_value
        for fast_value, slow_value in zip(fast_ema, slow_ema, strict=True)
    )

    computable_macd_values = tuple(value for value in macd_line if value is not None)
    signal_values = exponential_moving_average(computable_macd_values, period=signal_period)
    signal_iterator = iter(signal_values)
    signal_line = tuple(
        None if macd_value is None else next(signal_iterator) for macd_value in macd_line
    )
    histogram = tuple(
        None if macd_value is None or signal_value is None else macd_value - signal_value
        for macd_value, signal_value in zip(macd_line, signal_line, strict=True)
    )

    return MacdResult(macd_line=macd_line, signal_line=signal_line, histogram=histogram)


def average_true_range(
    candles: Sequence[CandleInput], *, period: int = 14
) -> tuple[Decimal | None, ...]:
    """Return an input-aligned Average True Range over OHLC candles.

    True range is the greatest of current high-low, current high minus previous
    close, and current low minus previous close in absolute terms. The first ATR
    value is seeded with the simple mean of the initial ``period`` true ranges;
    subsequent values use Wilder smoothing.
    """

    _validate_period(period)
    if not candles:
        return ()

    true_ranges = _true_ranges(candles)
    atr_values: list[Decimal | None] = [None] * min(period - 1, len(true_ranges))
    if len(true_ranges) < period:
        return tuple(atr_values)

    decimal_period = Decimal(period)
    previous_atr = sum(true_ranges[:period], Decimal("0")) / decimal_period
    atr_values.append(previous_atr)

    for true_range in true_ranges[period:]:
        previous_atr = (
            (previous_atr * Decimal(period - 1)) + true_range
        ) / decimal_period
        atr_values.append(previous_atr)

    return tuple(atr_values)


def _validate_period(period: int) -> None:
    if period <= 0:
        raise ValueError("period must be positive")


def _validate_macd_periods(
    fast_period: int, slow_period: int, signal_period: int
) -> None:
    _validate_period(fast_period)
    _validate_period(slow_period)
    _validate_period(signal_period)
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period")


def _rsi_from_average_gain_loss(average_gain: Decimal, average_loss: Decimal) -> Decimal:
    if average_loss == 0:
        if average_gain == 0:
            return Decimal("50")
        return Decimal("100")

    relative_strength = average_gain / average_loss
    return Decimal("100") - (Decimal("100") / (Decimal("1") + relative_strength))


def _true_ranges(candles: Sequence[CandleInput]) -> tuple[Decimal, ...]:
    true_ranges: list[Decimal] = []
    previous_close: Decimal | None = None
    for candle in candles:
        high_low_range = candle.high - candle.low
        if previous_close is None:
            true_range = high_low_range
        else:
            true_range = max(
                high_low_range,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        true_ranges.append(true_range)
        previous_close = candle.close
    return tuple(true_ranges)


def _coerce_prices(values: Sequence[PriceInput]) -> tuple[Decimal, ...]:
    return tuple(_coerce_price(value) for value in values)


def _coerce_price(value: PriceInput) -> Decimal:
    if isinstance(value, Candle):
        return value.close
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
