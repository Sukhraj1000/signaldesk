"""Deterministic technical-analysis indicator calculations."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Literal, NamedTuple

from signaldesk_backend.models import Candle

PriceInput = Candle | Decimal | int | float | str
CandleInput = Candle


class FibonacciRetracementLevel(NamedTuple):
    """A deterministic retracement level for a validated swing range."""

    ratio: Decimal
    percent: Decimal
    price: Decimal
    direction: Literal["up", "down"]
    swing_start: Decimal
    swing_end: Decimal


class MacdResult(NamedTuple):
    """Input-aligned MACD indicator series."""

    macd_line: tuple[Decimal | None, ...]
    signal_line: tuple[Decimal | None, ...]
    histogram: tuple[Decimal | None, ...]


class SwingPoint(NamedTuple):
    """A local swing high or low detected from a candle series."""

    kind: Literal["high", "low"]
    candle_index: int
    timestamp: datetime
    price: Decimal
    candle: Candle


class LevelZone(NamedTuple):
    """A clustered support or resistance price area backed by swing points."""

    kind: Literal["support", "resistance"]
    lower_bound: Decimal
    upper_bound: Decimal
    representative_price: Decimal
    evidence_count: int
    first_candle_index: int
    last_candle_index: int
    touches: tuple[SwingPoint, ...]


class SupportResistanceZones(NamedTuple):
    """Support and resistance zones detected from swing highs and lows."""

    support: tuple[LevelZone, ...]
    resistance: tuple[LevelZone, ...]


class ConfirmationInvalidationLevel(NamedTuple):
    """A traceable deterministic setup level derived from existing TA artifacts."""

    kind: Literal["confirmation", "invalidation"]
    price: Decimal
    source_rule: str
    source_level: str
    reason: str


class ConfirmationInvalidationLevels(NamedTuple):
    """Nearest deterministic confirmation and invalidation levels, if available."""

    confirmation: ConfirmationInvalidationLevel | None
    invalidation: ConfirmationInvalidationLevel | None


class RegimeClassification(NamedTuple):
    """A traceable deterministic market-regime label."""

    regime: str
    source_rule: str
    reason: str


class DeterministicTechnicalEvent(NamedTuple):
    """A traceable technical event emitted by a deterministic rule."""

    event_type: str
    timestamp: datetime
    candle_index: int
    severity: Literal["info", "bullish", "bearish", "warning"]
    source_rule: str
    source_indicators: tuple[str, ...]
    reason: str
    price: Decimal
    invalidation_condition: str | None = None


FIBONACCI_RETRACEMENT_RATIOS: tuple[Decimal, ...] = (
    Decimal("0.236"),
    Decimal("0.382"),
    Decimal("0.5"),
    Decimal("0.618"),
    Decimal("0.786"),
)


def calculate_fibonacci_retracement_levels(
    swing_start: PriceInput,
    swing_end: PriceInput,
) -> tuple[FibonacciRetracementLevel, ...]:
    """Return common Fibonacci retracement levels for a swing range.

    ``swing_start`` and ``swing_end`` are ordered swing endpoints. An upward
    move starts at the swing low and ends at the swing high, so retracement
    levels are below the high. A downward move starts at the swing high and ends
    at the swing low, so retracement levels are above the low.
    """

    start = _coerce_price(swing_start)
    end = _coerce_price(swing_end)
    if start == end:
        raise ValueError("swing range must not be zero-width")

    direction: Literal["up", "down"] = "up" if start < end else "down"
    swing_range = abs(end - start)
    levels: list[FibonacciRetracementLevel] = []
    for ratio in FIBONACCI_RETRACEMENT_RATIOS:
        retracement_distance = swing_range * ratio
        price = end - retracement_distance if direction == "up" else end + retracement_distance
        levels.append(
            FibonacciRetracementLevel(
                ratio=ratio,
                percent=ratio * Decimal("100"),
                price=price,
                direction=direction,
                swing_start=start,
                swing_end=end,
            )
        )
    return tuple(levels)


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
        previous_atr = ((previous_atr * Decimal(period - 1)) + true_range) / decimal_period
        atr_values.append(previous_atr)

    return tuple(atr_values)


def volume_moving_average(
    candles: Sequence[CandleInput], *, period: int = 20
) -> tuple[Decimal | None, ...]:
    """Return an input-aligned simple moving average of candle volume."""

    _validate_period(period)
    if not candles:
        return ()

    volumes = _coerce_volumes(candles)
    averages: list[Decimal | None] = []
    rolling_sum = Decimal("0")
    decimal_period = Decimal(period)
    for index, volume in enumerate(volumes):
        rolling_sum += volume
        if index >= period:
            rolling_sum -= volumes[index - period]
        if index < period - 1:
            averages.append(None)
        else:
            averages.append(rolling_sum / decimal_period)
    return tuple(averages)


def relative_volume(
    candles: Sequence[CandleInput], *, period: int = 20
) -> tuple[Decimal | None, ...]:
    """Return volume divided by the prior trailing average volume.

    Entries are ``None`` until ``period`` prior candles are available. If the
    trailing average is zero, ``None`` is returned to avoid division by zero.
    """

    _validate_period(period)
    if not candles:
        return ()

    volumes = _coerce_volumes(candles)
    relative_values: list[Decimal | None] = []
    rolling_sum = Decimal("0")
    decimal_period = Decimal(period)
    for index, volume in enumerate(volumes):
        if index < period:
            relative_values.append(None)
        else:
            trailing_average = rolling_sum / decimal_period
            relative_values.append(None if trailing_average == 0 else volume / trailing_average)
        rolling_sum += volume
        if index >= period:
            rolling_sum -= volumes[index - period]
    return tuple(relative_values)


def classify_trend_regime(
    values: Sequence[PriceInput], *, short_period: int = 20, long_period: int = 50
) -> RegimeClassification:
    """Classify trend from deterministic moving-average alignment.

    The rule intentionally uses only canonical close prices: uptrend requires
    close > short SMA > long SMA, downtrend requires close < short SMA < long
    SMA, and ties/mixed states are sideways. Insufficient warmup returns
    ``unknown`` with an explicit source rule rather than inventing context.
    """

    _validate_period(short_period)
    _validate_period(long_period)
    if short_period >= long_period:
        raise ValueError("short_period must be less than long_period")

    closes = _coerce_prices(values)
    if len(closes) < long_period:
        return RegimeClassification(
            regime="unknown",
            source_rule="insufficient_history_for_trend_regime",
            reason=(
                f"Need at least {long_period} closes to classify trend; received {len(closes)}."
            ),
        )

    short_average = simple_moving_average(closes, period=short_period)[-1]
    long_average = simple_moving_average(closes, period=long_period)[-1]
    latest_close = closes[-1]
    if short_average is None or long_average is None:
        return RegimeClassification(
            regime="unknown",
            source_rule="unavailable_moving_average_for_trend_regime",
            reason="Moving-average warmup did not produce a trend classification input.",
        )
    if latest_close > short_average > long_average:
        return RegimeClassification(
            regime="uptrend",
            source_rule="close_above_short_sma_above_long_sma",
            reason="Latest close is above the short SMA, and the short SMA is above the long SMA.",
        )
    if latest_close < short_average < long_average:
        return RegimeClassification(
            regime="downtrend",
            source_rule="close_below_short_sma_below_long_sma",
            reason="Latest close is below the short SMA, and the short SMA is below the long SMA.",
        )
    return RegimeClassification(
        regime="sideways",
        source_rule="mixed_or_tied_moving_average_alignment",
        reason="Moving-average alignment is mixed or tied, so no directional trend is confirmed.",
    )


def classify_volatility_regime(
    candles: Sequence[CandleInput], *, atr_period: int = 14, baseline_period: int = 50
) -> RegimeClassification:
    """Classify volatility from latest ATR versus its trailing baseline.

    ``volatility_expansion`` means latest ATR is at least 1.5x the trailing ATR
    baseline; ``volatility_compression`` means latest ATR is at most 0.75x that
    baseline. Flat zero-range candles are classified as compression rather than
    treated as an error.
    """

    _validate_period(atr_period)
    _validate_period(baseline_period)
    required_candles = atr_period + baseline_period
    if len(candles) < required_candles:
        return RegimeClassification(
            regime="unknown",
            source_rule="insufficient_history_for_volatility_regime",
            reason=(
                f"Need at least {required_candles} candles to classify volatility; "
                f"received {len(candles)}."
            ),
        )

    atr_values = average_true_range(candles, period=atr_period)
    computable_atr_values = tuple(value for value in atr_values if value is not None)
    baseline_window = computable_atr_values[-(baseline_period + 1) :]
    if len(baseline_window) < baseline_period + 1:
        return RegimeClassification(
            regime="unknown",
            source_rule="unavailable_atr_baseline_for_volatility_regime",
            reason="ATR warmup did not produce enough values for the volatility baseline.",
        )
    historical_baseline_values = baseline_window[:-1]
    latest_atr = baseline_window[-1]
    baseline_atr = sum(historical_baseline_values, Decimal("0")) / Decimal(
        len(historical_baseline_values)
    )
    if baseline_atr == 0:
        if latest_atr == 0:
            return RegimeClassification(
                regime="volatility_compression",
                source_rule="zero_latest_atr_and_zero_atr_baseline",
                reason=(
                    "Latest ATR and its trailing baseline are zero, indicating a flat "
                    "volatility regime."
                ),
            )
        return RegimeClassification(
            regime="volatility_expansion",
            source_rule="positive_latest_atr_against_zero_atr_baseline",
            reason="Latest ATR is positive after a zero ATR baseline.",
        )

    relative_atr = latest_atr / baseline_atr
    if relative_atr >= Decimal("1.5"):
        return RegimeClassification(
            regime="volatility_expansion",
            source_rule="latest_atr_at_least_1_5x_trailing_baseline",
            reason="Latest ATR is at least 1.5x its trailing baseline.",
        )
    if relative_atr <= Decimal("0.75"):
        return RegimeClassification(
            regime="volatility_compression",
            source_rule="latest_atr_at_most_0_75x_trailing_baseline",
            reason="Latest ATR is at most 0.75x its trailing baseline.",
        )
    return RegimeClassification(
        regime="normal_volatility",
        source_rule="latest_atr_within_trailing_baseline_band",
        reason="Latest ATR is between 0.75x and 1.5x its trailing baseline.",
    )


def classify_volume_regime(
    candles: Sequence[CandleInput], *, period: int = 20
) -> RegimeClassification:
    """Classify volume from latest volume versus prior trailing average volume."""

    _validate_period(period)
    if len(candles) <= period:
        return RegimeClassification(
            regime="unknown",
            source_rule="insufficient_history_for_volume_regime",
            reason=(
                f"Need more than {period} candles to classify relative volume; "
                f"received {len(candles)}."
            ),
        )

    latest_relative_volume = relative_volume(candles, period=period)[-1]
    if latest_relative_volume is None:
        return RegimeClassification(
            regime="unknown",
            source_rule="unavailable_relative_volume_for_volume_regime",
            reason=(
                "Relative volume is unavailable, likely because the trailing volume "
                "baseline is zero."
            ),
        )
    if latest_relative_volume >= Decimal("1.5"):
        return RegimeClassification(
            regime="high_volume",
            source_rule="latest_volume_at_least_1_5x_prior_average",
            reason="Latest volume is at least 1.5x its prior trailing average.",
        )
    if latest_relative_volume <= Decimal("0.75"):
        return RegimeClassification(
            regime="low_volume",
            source_rule="latest_volume_at_most_0_75x_prior_average",
            reason="Latest volume is at most 0.75x its prior trailing average.",
        )
    return RegimeClassification(
        regime="normal_volume",
        source_rule="latest_volume_within_prior_average_band",
        reason="Latest volume is between 0.75x and 1.5x its prior trailing average.",
    )


def detect_moving_average_cross_events(
    candles: Sequence[CandleInput], *, period: int = 20
) -> tuple[DeterministicTechnicalEvent, ...]:
    """Detect close-price reclaim/loss events around a moving average.

    A ``reclaimed_moving_average`` event is emitted when the prior close is at or
    below the prior SMA and the latest close is above the latest SMA. A
    ``lost_moving_average`` event is emitted for the inverse transition. Warmup
    periods return no events rather than inferred context.
    """

    _validate_period(period)
    if len(candles) < period + 1:
        return ()

    closes = tuple(candle.close for candle in candles)
    averages = simple_moving_average(closes, period=period)
    previous_average = averages[-2]
    latest_average = averages[-1]
    if previous_average is None or latest_average is None:
        return ()

    previous_close = closes[-2]
    latest_candle = candles[-1]
    latest_close = latest_candle.close
    indicator_name = f"sma_{period}"

    if previous_close <= previous_average and latest_close > latest_average:
        return (
            DeterministicTechnicalEvent(
                event_type="reclaimed_moving_average",
                timestamp=latest_candle.timestamp,
                candle_index=len(candles) - 1,
                severity="bullish",
                source_rule="close_crossed_above_sma",
                source_indicators=(indicator_name,),
                reason=(
                    f"Latest close {latest_close} moved above {indicator_name} "
                    f"{latest_average} after the prior close was not above its SMA."
                ),
                price=latest_close,
                invalidation_condition=(
                    f"A close back below {indicator_name} {latest_average} would invalidate "
                    "the reclaim event."
                ),
            ),
        )
    if previous_close >= previous_average and latest_close < latest_average:
        return (
            DeterministicTechnicalEvent(
                event_type="lost_moving_average",
                timestamp=latest_candle.timestamp,
                candle_index=len(candles) - 1,
                severity="bearish",
                source_rule="close_crossed_below_sma",
                source_indicators=(indicator_name,),
                reason=(
                    f"Latest close {latest_close} moved below {indicator_name} "
                    f"{latest_average} after the prior close was not below its SMA."
                ),
                price=latest_close,
                invalidation_condition=(
                    f"A close back above {indicator_name} {latest_average} would invalidate "
                    "the loss event."
                ),
            ),
        )
    return ()


def detect_trend_regime_shift_events(
    candles: Sequence[CandleInput], *, short_period: int = 20, long_period: int = 50
) -> tuple[DeterministicTechnicalEvent, ...]:
    """Detect a latest-candle trend regime shift from MA alignment.

    The rule compares the deterministic trend classification before and after
    the latest candle. It emits only when both classifications are available and
    the regime changes, so insufficient warmup returns no event rather than
    inferred context.
    """

    _validate_period(short_period)
    _validate_period(long_period)
    if short_period >= long_period:
        raise ValueError("short_period must be less than long_period")
    if len(candles) < long_period + 1:
        return ()

    previous_regime = classify_trend_regime(
        tuple(candle.close for candle in candles[:-1]),
        short_period=short_period,
        long_period=long_period,
    )
    latest_regime = classify_trend_regime(
        tuple(candle.close for candle in candles),
        short_period=short_period,
        long_period=long_period,
    )
    if "unknown" in {previous_regime.regime, latest_regime.regime}:
        return ()
    if previous_regime.regime == latest_regime.regime:
        return ()

    latest_candle = candles[-1]
    severity: Literal["info", "bullish", "bearish", "warning"] = "info"
    if latest_regime.regime == "uptrend":
        severity = "bullish"
    elif latest_regime.regime == "downtrend":
        severity = "bearish"

    return (
        DeterministicTechnicalEvent(
            event_type="trend_regime_shift",
            timestamp=latest_candle.timestamp,
            candle_index=len(candles) - 1,
            severity=severity,
            source_rule="latest_candle_changed_trend_regime_classification",
            source_indicators=(f"sma_{short_period}", f"sma_{long_period}"),
            reason=(
                f"Trend regime shifted from {previous_regime.regime} to "
                f"{latest_regime.regime}: {latest_regime.reason}"
            ),
            price=latest_candle.close,
            invalidation_condition=(
                f"A later close changing the deterministic trend regime away from "
                f"{latest_regime.regime} would end this regime-shift condition."
            ),
        ),
    )


def detect_breakout_breakdown_events(
    candles: Sequence[CandleInput],
    *,
    levels: ConfirmationInvalidationLevels | None = None,
    window: int = 2,
    lookback: int | None = None,
    lookahead: int | None = None,
) -> tuple[DeterministicTechnicalEvent, ...]:
    """Detect latest-candle breakout or breakdown through setup levels.

    Breakouts are emitted when the latest close crosses above the prior
    deterministic confirmation level derived from resistance. Breakdowns are
    emitted when the latest close crosses below the prior deterministic
    invalidation level derived from support. Missing levels, insufficient
    history, or closes already beyond the level on the prior candle return no
    event rather than inferred context.
    """

    if len(candles) < 2:
        return ()

    resolved_levels = levels or derive_confirmation_invalidation_levels(
        candles[:-1],
        window=window,
        lookback=lookback,
        lookahead=lookahead,
    )
    previous_close = candles[-2].close
    latest_candle = candles[-1]
    latest_close = latest_candle.close
    events: list[DeterministicTechnicalEvent] = []

    confirmation = resolved_levels.confirmation
    if (
        confirmation is not None
        and previous_close <= confirmation.price
        and latest_close > confirmation.price
    ):
        events.append(
            DeterministicTechnicalEvent(
                event_type="breakout",
                timestamp=latest_candle.timestamp,
                candle_index=len(candles) - 1,
                severity="bullish",
                source_rule="latest_close_crossed_above_confirmation_level",
                source_indicators=(confirmation.source_level,),
                reason=(
                    f"Latest close {latest_close} crossed above confirmation level "
                    f"{confirmation.price} from {confirmation.source_level}."
                ),
                price=latest_close,
                invalidation_condition=(
                    f"A close back below confirmation level {confirmation.price} would "
                    "invalidate the breakout event."
                ),
            )
        )

    invalidation = resolved_levels.invalidation
    if (
        invalidation is not None
        and previous_close >= invalidation.price
        and latest_close < invalidation.price
    ):
        events.append(
            DeterministicTechnicalEvent(
                event_type="breakdown",
                timestamp=latest_candle.timestamp,
                candle_index=len(candles) - 1,
                severity="bearish",
                source_rule="latest_close_crossed_below_invalidation_level",
                source_indicators=(invalidation.source_level,),
                reason=(
                    f"Latest close {latest_close} crossed below invalidation level "
                    f"{invalidation.price} from {invalidation.source_level}."
                ),
                price=latest_close,
                invalidation_condition=(
                    f"A close back above invalidation level {invalidation.price} would "
                    "invalidate the breakdown event."
                ),
            )
        )

    return tuple(events)


def detect_relative_volume_spike_events(
    candles: Sequence[CandleInput], *, period: int = 20, threshold: Decimal = Decimal("1.5")
) -> tuple[DeterministicTechnicalEvent, ...]:
    """Detect a latest-candle relative volume spike from a prior trailing baseline.

    The event is emitted only when the latest candle volume is at least
    ``threshold`` times its prior trailing average volume. The rule uses the same
    prior-baseline relative volume calculation as ``classify_volume_regime`` so
    it does not silently include the latest candle in its own comparison window.
    Warmup periods, zero baselines, or non-spike values return no event.
    """

    _validate_period(period)
    if threshold <= Decimal("0"):
        raise ValueError("threshold must be positive")
    if len(candles) <= period:
        return ()

    latest_relative_volume = relative_volume(candles, period=period)[-1]
    if latest_relative_volume is None or latest_relative_volume < threshold:
        return ()

    latest_candle = candles[-1]
    average_volume = volume_moving_average(candles[:-1], period=period)[-1]
    if average_volume is None:
        return ()

    relative_volume_indicator = f"relative_volume_{period}"
    return (
        DeterministicTechnicalEvent(
            event_type="relative_volume_spike",
            timestamp=latest_candle.timestamp,
            candle_index=len(candles) - 1,
            severity="info",
            source_rule="latest_volume_at_least_threshold_x_prior_average",
            source_indicators=(relative_volume_indicator,),
            reason=(
                f"Latest volume {latest_candle.volume} is {latest_relative_volume}x its "
                f"prior {period}-candle average volume {average_volume}."
            ),
            price=latest_candle.close,
            invalidation_condition=(
                f"Relative volume below {threshold}x the prior {period}-candle average "
                "would end the spike condition."
            ),
        ),
    )


def detect_overextension_events(
    candles: Sequence[CandleInput],
    *,
    ma_period: int = 20,
    atr_period: int = 14,
    atr_multiple: Decimal = Decimal("2"),
) -> tuple[DeterministicTechnicalEvent, ...]:
    """Detect latest-candle price overextension from SMA plus ATR distance.

    The rule emits an upside event when the latest close is at least
    ``atr_multiple`` ATR above the selected SMA, and a downside event when it is
    at least that far below the SMA. Warmup periods, zero ATR, or prices inside
    the band return no event rather than inferred context.
    """

    _validate_period(ma_period)
    _validate_period(atr_period)
    if atr_multiple <= Decimal("0"):
        raise ValueError("atr_multiple must be positive")
    if len(candles) < max(ma_period, atr_period):
        return ()

    closes = tuple(candle.close for candle in candles)
    latest_sma = simple_moving_average(closes, period=ma_period)[-1]
    latest_atr = average_true_range(candles, period=atr_period)[-1]
    if latest_sma is None or latest_atr is None or latest_atr == 0:
        return ()

    latest_candle = candles[-1]
    latest_close = latest_candle.close
    allowed_distance = latest_atr * atr_multiple
    upper_band = latest_sma + allowed_distance
    lower_band = latest_sma - allowed_distance
    source_indicators = (f"sma_{ma_period}", f"atr_{atr_period}")
    multiple_text = str(atr_multiple)

    if latest_close >= upper_band:
        return (
            DeterministicTechnicalEvent(
                event_type="overextension_up",
                timestamp=latest_candle.timestamp,
                candle_index=len(candles) - 1,
                severity="warning",
                source_rule="latest_close_at_least_atr_multiple_above_sma",
                source_indicators=source_indicators,
                reason=(
                    f"Latest close {latest_close} is at least {multiple_text}x ATR above "
                    f"sma_{ma_period} {latest_sma}; latest ATR is {latest_atr}."
                ),
                price=latest_close,
                invalidation_condition=(
                    f"A close back within {multiple_text}x ATR of sma_{ma_period} "
                    f"{latest_sma} would end the upside overextension condition."
                ),
            ),
        )
    if latest_close <= lower_band:
        return (
            DeterministicTechnicalEvent(
                event_type="overextension_down",
                timestamp=latest_candle.timestamp,
                candle_index=len(candles) - 1,
                severity="warning",
                source_rule="latest_close_at_least_atr_multiple_below_sma",
                source_indicators=source_indicators,
                reason=(
                    f"Latest close {latest_close} is at least {multiple_text}x ATR below "
                    f"sma_{ma_period} {latest_sma}; latest ATR is {latest_atr}."
                ),
                price=latest_close,
                invalidation_condition=(
                    f"A close back within {multiple_text}x ATR of sma_{ma_period} "
                    f"{latest_sma} would end the downside overextension condition."
                ),
            ),
        )
    return ()


def detect_volatility_regime_events(
    candles: Sequence[CandleInput],
    *,
    atr_period: int = 14,
    baseline_period: int = 50,
    expansion_threshold: Decimal = Decimal("1.5"),
    compression_threshold: Decimal = Decimal("0.75"),
) -> tuple[DeterministicTechnicalEvent, ...]:
    """Detect latest-candle volatility expansion or compression from ATR.

    The rule compares the latest ATR to a trailing ATR baseline that excludes the
    latest candle. Expansion emits when latest ATR is at least
    ``expansion_threshold`` times that baseline; compression emits when latest
    ATR is at most ``compression_threshold`` times it. Warmup periods and normal
    values return no event rather than inferred context.
    """

    _validate_period(atr_period)
    _validate_period(baseline_period)
    if expansion_threshold <= Decimal("0") or compression_threshold <= Decimal("0"):
        raise ValueError("volatility thresholds must be positive")
    if compression_threshold >= expansion_threshold:
        raise ValueError("compression_threshold must be less than expansion_threshold")

    required_candles = atr_period + baseline_period
    if len(candles) < required_candles:
        return ()

    atr_values = tuple(
        value
        for value in average_true_range(candles, period=atr_period)
        if value is not None
    )
    baseline_window = atr_values[-(baseline_period + 1) :]
    if len(baseline_window) < baseline_period + 1:
        return ()

    historical_baseline_values = baseline_window[:-1]
    latest_atr = baseline_window[-1]
    baseline_atr = sum(historical_baseline_values, Decimal("0")) / Decimal(
        len(historical_baseline_values)
    )
    latest_candle = candles[-1]
    atr_indicator = f"atr_{atr_period}"

    if baseline_atr == 0:
        if latest_atr == 0:
            return (
                DeterministicTechnicalEvent(
                    event_type="volatility_compression",
                    timestamp=latest_candle.timestamp,
                    candle_index=len(candles) - 1,
                    severity="info",
                    source_rule="zero_latest_atr_and_zero_atr_baseline",
                    source_indicators=(atr_indicator,),
                    reason="Latest ATR and its trailing baseline are both zero.",
                    price=latest_candle.close,
                    invalidation_condition=(
                        "A positive ATR would end the flat compression condition."
                    ),
                ),
            )
        return (
            DeterministicTechnicalEvent(
                event_type="volatility_expansion",
                timestamp=latest_candle.timestamp,
                candle_index=len(candles) - 1,
                severity="warning",
                source_rule="positive_latest_atr_against_zero_atr_baseline",
                source_indicators=(atr_indicator,),
                reason=f"Latest ATR {latest_atr} is positive after a zero ATR baseline.",
                price=latest_candle.close,
                invalidation_condition="A return to zero ATR would end the expansion condition.",
            ),
        )

    relative_atr = latest_atr / baseline_atr
    if relative_atr >= expansion_threshold:
        return (
            DeterministicTechnicalEvent(
                event_type="volatility_expansion",
                timestamp=latest_candle.timestamp,
                candle_index=len(candles) - 1,
                severity="warning",
                source_rule="latest_atr_at_least_threshold_x_trailing_baseline",
                source_indicators=(atr_indicator,),
                reason=(
                    f"Latest ATR {latest_atr} is {relative_atr}x its trailing "
                    f"{baseline_period}-ATR baseline {baseline_atr}."
                ),
                price=latest_candle.close,
                invalidation_condition=(
                    f"ATR below {expansion_threshold}x the trailing {baseline_period}-ATR "
                    "baseline would end the expansion condition."
                ),
            ),
        )
    if relative_atr <= compression_threshold:
        return (
            DeterministicTechnicalEvent(
                event_type="volatility_compression",
                timestamp=latest_candle.timestamp,
                candle_index=len(candles) - 1,
                severity="info",
                source_rule="latest_atr_at_most_threshold_x_trailing_baseline",
                source_indicators=(atr_indicator,),
                reason=(
                    f"Latest ATR {latest_atr} is {relative_atr}x its trailing "
                    f"{baseline_period}-ATR baseline {baseline_atr}."
                ),
                price=latest_candle.close,
                invalidation_condition=(
                    f"ATR above {compression_threshold}x the trailing {baseline_period}-ATR "
                    "baseline would end the compression condition."
                ),
            ),
        )
    return ()


def detect_swing_highs(
    candles: Sequence[CandleInput],
    *,
    window: int = 2,
    lookback: int | None = None,
    lookahead: int | None = None,
) -> tuple[SwingPoint, ...]:
    """Return local swing highs with a full surrounding candle window.

    A swing high is a candle whose high is strictly greater than every high in
    the surrounding candles. By default ``window`` is used for both the backward
    and forward comparison windows; callers may pass ``lookback`` and/or
    ``lookahead`` for asymmetric confirmation. Equal highs are treated as ties
    and are not reported so flat/tie behavior is deterministic.
    """

    return _detect_swings(
        candles,
        window=window,
        lookback=lookback,
        lookahead=lookahead,
        kind="high",
    )


def detect_swing_lows(
    candles: Sequence[CandleInput],
    *,
    window: int = 2,
    lookback: int | None = None,
    lookahead: int | None = None,
) -> tuple[SwingPoint, ...]:
    """Return local swing lows with a full surrounding candle window.

    A swing low is a candle whose low is strictly lower than every low in the
    surrounding candles. By default ``window`` is used for both the backward and
    forward comparison windows; callers may pass ``lookback`` and/or
    ``lookahead`` for asymmetric confirmation. Equal lows are treated as ties and
    are not reported so flat/tie behavior is deterministic.
    """

    return _detect_swings(
        candles,
        window=window,
        lookback=lookback,
        lookahead=lookahead,
        kind="low",
    )


def detect_swing_points(
    candles: Sequence[CandleInput],
    *,
    window: int = 2,
    lookback: int | None = None,
    lookahead: int | None = None,
) -> tuple[SwingPoint, ...]:
    """Return swing highs and lows ordered by their original candle index."""

    swing_points = (
        *detect_swing_highs(
            candles,
            window=window,
            lookback=lookback,
            lookahead=lookahead,
        ),
        *detect_swing_lows(
            candles,
            window=window,
            lookback=lookback,
            lookahead=lookahead,
        ),
    )
    return tuple(sorted(swing_points, key=lambda point: (point.candle_index, point.kind)))


def detect_support_resistance_zones(
    candles: Sequence[CandleInput] = (),
    *,
    swing_points: Sequence[SwingPoint] | None = None,
    tolerance: Decimal | int | float | str = Decimal("0.01"),
    tolerance_mode: Literal["percent", "absolute"] = "percent",
    window: int = 2,
    lookback: int | None = None,
    lookahead: int | None = None,
) -> SupportResistanceZones:
    """Cluster nearby swing lows as support and swing highs as resistance.

    Callers may pass precomputed ``swing_points`` or raw ``candles``. In percent
    mode, ``tolerance`` is interpreted as a fraction of the cluster's current
    representative price (``0.01`` means 1%). In absolute mode, it is an exact
    price distance. Empty candle or swing input returns empty support and
    resistance tuples.
    """

    resolved_tolerance = _coerce_price(tolerance)
    if resolved_tolerance < 0:
        raise ValueError("tolerance must be non-negative")
    if tolerance_mode not in {"percent", "absolute"}:
        raise ValueError("tolerance_mode must be percent or absolute")

    resolved_swing_points = (
        tuple(swing_points)
        if swing_points is not None
        else detect_swing_points(
            candles,
            window=window,
            lookback=lookback,
            lookahead=lookahead,
        )
    )
    if not resolved_swing_points:
        return SupportResistanceZones(support=(), resistance=())

    support_points = tuple(point for point in resolved_swing_points if point.kind == "low")
    resistance_points = tuple(point for point in resolved_swing_points if point.kind == "high")
    return SupportResistanceZones(
        support=_cluster_level_zones(
            support_points,
            zone_kind="support",
            tolerance=resolved_tolerance,
            tolerance_mode=tolerance_mode,
        ),
        resistance=_cluster_level_zones(
            resistance_points,
            zone_kind="resistance",
            tolerance=resolved_tolerance,
            tolerance_mode=tolerance_mode,
        ),
    )


def derive_confirmation_invalidation_levels(
    candles: Sequence[CandleInput],
    *,
    zones: SupportResistanceZones | None = None,
    window: int = 2,
    lookback: int | None = None,
    lookahead: int | None = None,
) -> ConfirmationInvalidationLevels:
    """Derive nearest traceable setup levels from support/resistance artifacts.

    The rule is intentionally small and deterministic: confirmation is the
    nearest resistance zone above the latest close, and invalidation is the
    nearest support zone below the latest close. If a side is unavailable, that
    side is returned as ``None`` rather than fabricated from narrative context.
    """

    if not candles:
        return ConfirmationInvalidationLevels(confirmation=None, invalidation=None)

    latest_close = candles[-1].close
    resolved_zones = zones or detect_support_resistance_zones(
        candles,
        window=window,
        lookback=lookback,
        lookahead=lookahead,
    )
    confirmation_zone = _nearest_zone_above(latest_close, resolved_zones.resistance)
    invalidation_zone = _nearest_zone_below(latest_close, resolved_zones.support)

    confirmation = (
        None
        if confirmation_zone is None
        else ConfirmationInvalidationLevel(
            kind="confirmation",
            price=confirmation_zone.representative_price,
            source_rule="nearest_resistance_above_latest_close",
            source_level=_zone_reference(confirmation_zone),
            reason=(
                "Latest close remains below this resistance zone; a move through "
                "it would confirm upside continuation."
            ),
        )
    )
    invalidation = (
        None
        if invalidation_zone is None
        else ConfirmationInvalidationLevel(
            kind="invalidation",
            price=invalidation_zone.representative_price,
            source_rule="nearest_support_below_latest_close",
            source_level=_zone_reference(invalidation_zone),
            reason=(
                "Latest close remains above this support zone; a break below it "
                "would invalidate the current technical setup."
            ),
        )
    )
    return ConfirmationInvalidationLevels(
        confirmation=confirmation,
        invalidation=invalidation,
    )


def _nearest_zone_above(price: Decimal, zones: Sequence[LevelZone]) -> LevelZone | None:
    candidates = tuple(zone for zone in zones if zone.representative_price > price)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda zone: (zone.representative_price - price, -zone.evidence_count),
    )


def _nearest_zone_below(price: Decimal, zones: Sequence[LevelZone]) -> LevelZone | None:
    candidates = tuple(zone for zone in zones if zone.representative_price < price)
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda zone: (price - zone.representative_price, -zone.evidence_count),
    )


def _zone_reference(zone: LevelZone) -> str:
    return f"{zone.kind}_zone[{zone.lower_bound},{zone.upper_bound}] touches={zone.evidence_count}"


def _cluster_level_zones(
    points: Sequence[SwingPoint],
    *,
    zone_kind: Literal["support", "resistance"],
    tolerance: Decimal,
    tolerance_mode: Literal["percent", "absolute"],
) -> tuple[LevelZone, ...]:
    if not points:
        return ()

    sorted_points = sorted(points, key=lambda point: (point.price, point.candle_index))
    clusters: list[list[SwingPoint]] = []
    current_cluster: list[SwingPoint] = []
    for point in sorted_points:
        if not current_cluster or _point_fits_cluster(
            point,
            current_cluster,
            tolerance=tolerance,
            tolerance_mode=tolerance_mode,
        ):
            current_cluster.append(point)
        else:
            clusters.append(current_cluster)
            current_cluster = [point]
    if current_cluster:
        clusters.append(current_cluster)

    zones = tuple(_zone_from_cluster(cluster, zone_kind=zone_kind) for cluster in clusters)
    return tuple(
        sorted(
            zones,
            key=lambda zone: (-zone.evidence_count, zone.representative_price),
        )
    )


def _point_fits_cluster(
    point: SwingPoint,
    cluster: Sequence[SwingPoint],
    *,
    tolerance: Decimal,
    tolerance_mode: Literal["percent", "absolute"],
) -> bool:
    prices = tuple(cluster_point.price for cluster_point in cluster)
    lower_bound = min(prices)
    upper_bound = max(prices)
    representative_price = sum(prices, Decimal("0")) / Decimal(len(prices))
    allowed_distance = (
        tolerance if tolerance_mode == "absolute" else abs(representative_price) * tolerance
    )
    return lower_bound - allowed_distance <= point.price <= upper_bound + allowed_distance


def _zone_from_cluster(
    cluster: Sequence[SwingPoint],
    *,
    zone_kind: Literal["support", "resistance"],
) -> LevelZone:
    touches = tuple(sorted(cluster, key=lambda point: point.candle_index))
    prices = tuple(point.price for point in touches)
    candle_indexes = tuple(point.candle_index for point in touches)
    return LevelZone(
        kind=zone_kind,
        lower_bound=min(prices),
        upper_bound=max(prices),
        representative_price=sum(prices, Decimal("0")) / Decimal(len(prices)),
        evidence_count=len(touches),
        first_candle_index=min(candle_indexes),
        last_candle_index=max(candle_indexes),
        touches=touches,
    )


def _validate_period(period: int) -> None:
    if period <= 0:
        raise ValueError("period must be positive")


def _validate_swing_window(value: int, name: str) -> None:
    if value <= 0:
        raise ValueError(f"{name} must be positive")


def _resolve_swing_windows(
    *, window: int, lookback: int | None, lookahead: int | None
) -> tuple[int, int]:
    resolved_lookback = window if lookback is None else lookback
    resolved_lookahead = window if lookahead is None else lookahead
    _validate_swing_window(resolved_lookback, "lookback")
    _validate_swing_window(resolved_lookahead, "lookahead")
    return resolved_lookback, resolved_lookahead


def _detect_swings(
    candles: Sequence[CandleInput],
    *,
    window: int,
    lookback: int | None,
    lookahead: int | None,
    kind: Literal["high", "low"],
) -> tuple[SwingPoint, ...]:
    resolved_lookback, resolved_lookahead = _resolve_swing_windows(
        window=window,
        lookback=lookback,
        lookahead=lookahead,
    )
    if len(candles) < resolved_lookback + resolved_lookahead + 1:
        return ()

    swings: list[SwingPoint] = []
    for index in range(resolved_lookback, len(candles) - resolved_lookahead):
        candle = candles[index]
        neighbors = (
            *candles[index - resolved_lookback : index],
            *candles[index + 1 : index + resolved_lookahead + 1],
        )
        if kind == "high":
            price = candle.high
            if all(price > neighbor.high for neighbor in neighbors):
                swings.append(
                    SwingPoint(
                        kind=kind,
                        candle_index=index,
                        timestamp=candle.timestamp,
                        price=price,
                        candle=candle,
                    )
                )
        else:
            price = candle.low
            if all(price < neighbor.low for neighbor in neighbors):
                swings.append(
                    SwingPoint(
                        kind=kind,
                        candle_index=index,
                        timestamp=candle.timestamp,
                        price=price,
                        candle=candle,
                    )
                )
    return tuple(swings)


def _validate_macd_periods(fast_period: int, slow_period: int, signal_period: int) -> None:
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


def _coerce_volumes(candles: Sequence[CandleInput]) -> tuple[Decimal, ...]:
    return tuple(Decimal(candle.volume) for candle in candles)


def _coerce_price(value: PriceInput) -> Decimal:
    if isinstance(value, Candle):
        return value.close
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
