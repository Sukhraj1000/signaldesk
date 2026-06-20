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
        previous_atr = (
            (previous_atr * Decimal(period - 1)) + true_range
        ) / decimal_period
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
            relative_values.append(
                None if trailing_average == 0 else volume / trailing_average
            )
        rolling_sum += volume
        if index >= period:
            rolling_sum -= volumes[index - period]
    return tuple(relative_values)


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
    resistance_points = tuple(
        point for point in resolved_swing_points if point.kind == "high"
    )
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
        tolerance
        if tolerance_mode == "absolute"
        else abs(representative_price) * tolerance
    )
    return (
        lower_bound - allowed_distance <= point.price <= upper_bound + allowed_distance
    )


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


def _coerce_volumes(candles: Sequence[CandleInput]) -> tuple[Decimal, ...]:
    return tuple(Decimal(candle.volume) for candle in candles)


def _coerce_price(value: PriceInput) -> Decimal:
    if isinstance(value, Candle):
        return value.close
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))
