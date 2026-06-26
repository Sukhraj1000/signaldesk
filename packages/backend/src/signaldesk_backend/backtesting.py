"""Deterministic historical setup replay utilities.

This module evaluates already-labeled technical setups over historical candles.
It is intentionally provider-agnostic and does not model orders, fills, brokers,
position sizing, slippage, or recommendations.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from signaldesk_backend.models import Candle, Provenance, Symbol

_SETUP_LABEL_ALIASES = {
    "breakout": "breakout_watch",
    "breakout_watch": "breakout_watch",
    "breakdown": "breakdown_watch",
    "breakdown_watch": "breakdown_watch",
    "moving_average_reclaim": "moving_average_reclaim",
    "reclaimed_moving_average": "moving_average_reclaim",
    "moving_average_loss": "moving_average_loss",
    "lost_moving_average": "moving_average_loss",
    "relative_volume_spike": "relative_volume_spike",
    "volume_spike": "relative_volume_spike",
}


_RESEARCH_ONLY_LIMITATION = (
    "Historical setup replay is deterministic research only; "
    "it is not live trading or broker execution."
)


@dataclass(frozen=True, kw_only=True)
class SetupReplayMetrics:
    """Deterministic usefulness metrics for historical setup labels."""

    hit_rate: Decimal | None
    average_forward_return_by_horizon: Mapping[int, Decimal | None]
    false_breakout_rate: Decimal | None
    max_adverse_excursion: Decimal | None
    event_usefulness: Decimal | None
    data_availability_rate: Decimal


@dataclass(frozen=True, kw_only=True)
class SetupReplayWalkForwardWindow:
    """One chronological walk-forward validation window."""

    window_index: int
    signal_indices: tuple[int, ...]
    start_observed_at: datetime
    end_observed_at: datetime
    sample_size: int
    evaluable_signals: int
    metrics: SetupReplayMetrics


@dataclass(frozen=True, kw_only=True)
class SetupReplayObservation:
    """One setup label replayed from a candle index."""

    signal_index: int
    observed_at: datetime
    entry_close: Decimal
    forward_returns_by_horizon: Mapping[int, Decimal | None]
    hit: bool | None
    false_breakout: bool | None
    max_adverse_excursion: Decimal | None


@dataclass(frozen=True, kw_only=True)
class SetupReplayReport:
    """Historical setup replay report with provenance and limitations."""

    setup_label: str
    symbol: Symbol
    timeframe: str
    sample_size: int
    evaluable_signals: int
    horizons: tuple[int, ...]
    metrics: SetupReplayMetrics
    observations: tuple[SetupReplayObservation, ...]
    walk_forward_windows: tuple[SetupReplayWalkForwardWindow, ...]
    provenance: Provenance
    limitations: tuple[str, ...]
    unavailable_context: tuple[str, ...]


def derive_setup_signal_indices(
    *,
    setup_label: str,
    candles: Sequence[Candle],
    lookback: int = 20,
    volume_spike_threshold: Decimal = Decimal("1.5"),
) -> tuple[int, ...]:
    """Derive historical signal indices for built-in deterministic setup labels."""

    normalized_label = _normalize_setup_label(setup_label)
    if normalized_label not in _SETUP_LABEL_ALIASES:
        supported = ", ".join(sorted(_SETUP_LABEL_ALIASES))
        raise ValueError(f"unsupported setup_label {setup_label!r}; supported labels: {supported}")
    normalized_label = _SETUP_LABEL_ALIASES[normalized_label]
    if lookback <= 0:
        raise ValueError("lookback must be a positive candle count")
    normalized_candles = tuple(candles)
    if len(normalized_candles) <= lookback:
        return ()

    signal_indices: list[int] = []
    for index in range(lookback, len(normalized_candles)):
        history = normalized_candles[index - lookback : index]
        previous = normalized_candles[index - 1]
        current = normalized_candles[index]
        if normalized_label == "breakout_watch":
            prior_high = max(candle.high for candle in history)
            if previous.close <= prior_high and current.close > prior_high:
                signal_indices.append(index)
        elif normalized_label == "breakdown_watch":
            prior_low = min(candle.low for candle in history)
            if previous.close >= prior_low and current.close < prior_low:
                signal_indices.append(index)
        elif normalized_label == "moving_average_reclaim":
            previous_average = _average_raw(tuple(candle.close for candle in history))
            latest_average = _average_raw(
                tuple(candle.close for candle in history[1:] + (current,))
            )
            if previous.close <= previous_average and current.close > latest_average:
                signal_indices.append(index)
        elif normalized_label == "moving_average_loss":
            previous_average = _average_raw(tuple(candle.close for candle in history))
            latest_average = _average_raw(
                tuple(candle.close for candle in history[1:] + (current,))
            )
            if previous.close >= previous_average and current.close < latest_average:
                signal_indices.append(index)
        elif normalized_label == "relative_volume_spike":
            average_volume = sum(candle.volume for candle in history) / Decimal(len(history))
            if average_volume > 0 and current.volume >= average_volume * volume_spike_threshold:
                signal_indices.append(index)
    return tuple(signal_indices)


def evaluate_setup_replay(
    *,
    setup_label: str,
    candles: Sequence[Candle],
    signal_indices: Sequence[int],
    horizons: Sequence[int] = (1, 5, 20),
    confirmation_level: Decimal | None = None,
    invalidation_level: Decimal | None = None,
    symbol: Symbol | None = None,
    provider: str = "local_fixture",
    source: str = "historical_candles",
    generated_at: datetime | None = None,
    timeframe: str = "1d",
    walk_forward_window_size: int | None = None,
    broker: str | None = None,
) -> SetupReplayReport:
    """Replay setup labels over historical candles and return deterministic metrics.

    ``signal_indices`` are zero-based candle positions where a setup label was
    known at the close of that candle. Each future horizon is evaluated only
    when the required forward candle exists; missing windows are surfaced as
    unavailable context and reflected in the data-availability rate.
    """

    if broker is not None:
        raise ValueError("setup replay must not include broker or execution assumptions")
    normalized_label = _normalize_setup_label(setup_label)
    normalized_horizons = _normalize_horizons(horizons)
    normalized_candles = tuple(candles)
    if not normalized_candles:
        raise ValueError("candles are required")
    report_symbol = symbol or normalized_candles[0].symbol
    _validate_candles(normalized_candles, report_symbol)
    normalized_indices = _normalize_signal_indices(signal_indices, len(normalized_candles))

    observations = tuple(
        _evaluate_observation(
            candles=normalized_candles,
            signal_index=signal_index,
            horizons=normalized_horizons,
            confirmation_level=confirmation_level,
            invalidation_level=invalidation_level,
        )
        for signal_index in normalized_indices
    )
    metrics, unavailable_context = _aggregate_metrics(observations, normalized_horizons)
    walk_forward_windows = _build_walk_forward_windows(
        observations=observations,
        horizons=normalized_horizons,
        window_size=walk_forward_window_size,
    )
    return SetupReplayReport(
        setup_label=normalized_label,
        symbol=report_symbol,
        timeframe=timeframe.strip() or "1d",
        sample_size=len(normalized_indices),
        evaluable_signals=sum(
            1
            for observation in observations
            if any(value is not None for value in observation.forward_returns_by_horizon.values())
        ),
        horizons=normalized_horizons,
        metrics=metrics,
        observations=observations,
        walk_forward_windows=walk_forward_windows,
        provenance=Provenance(
            provider=provider,
            source=source,
            generated_at=generated_at or normalized_candles[-1].timestamp,
            timeframe=timeframe.strip() or "1d",
            inputs=(report_symbol.ticker, normalized_label),
            warnings=unavailable_context,
        ),
        limitations=(_RESEARCH_ONLY_LIMITATION,),
        unavailable_context=unavailable_context,
    )


def _normalize_setup_label(setup_label: str) -> str:
    normalized_label = setup_label.strip().lower().replace(" ", "_").replace("-", "_")
    if not normalized_label:
        raise ValueError("setup_label is required")
    return _SETUP_LABEL_ALIASES.get(normalized_label, normalized_label)


def _normalize_horizons(horizons: Sequence[int]) -> tuple[int, ...]:
    normalized = tuple(sorted(set(horizons)))
    if not normalized or any(horizon <= 0 for horizon in normalized):
        raise ValueError("horizons must include positive forward candle counts")
    return normalized


def _validate_candles(candles: Sequence[Candle], symbol: Symbol) -> None:
    previous_timestamp: datetime | None = None
    for candle in candles:
        if candle.symbol != symbol:
            raise ValueError("all candles must use the same symbol as the replay report")
        if previous_timestamp is not None and candle.timestamp <= previous_timestamp:
            raise ValueError("candles must be sorted in strictly increasing timestamp order")
        previous_timestamp = candle.timestamp


def _normalize_signal_indices(signal_indices: Sequence[int], candle_count: int) -> tuple[int, ...]:
    normalized = tuple(signal_indices)
    if not normalized:
        raise ValueError("signal_indices are required")
    for signal_index in normalized:
        if signal_index < 0 or signal_index >= candle_count:
            raise ValueError("signal_indices must point at existing candles")
    return normalized


def _evaluate_observation(
    *,
    candles: Sequence[Candle],
    signal_index: int,
    horizons: tuple[int, ...],
    confirmation_level: Decimal | None,
    invalidation_level: Decimal | None,
) -> SetupReplayObservation:
    entry = candles[signal_index]
    forward_returns: dict[int, Decimal | None] = {}
    for horizon in horizons:
        forward_index = signal_index + horizon
        if forward_index >= len(candles):
            forward_returns[horizon] = None
        else:
            forward_returns[horizon] = _rate_of_return(entry.close, candles[forward_index].close)

    future_window = candles[signal_index + 1 : signal_index + 1 + max(horizons)]
    primary_forward_return = forward_returns[horizons[0]]
    if confirmation_level is not None and future_window:
        hit = any(candle.close >= confirmation_level for candle in future_window)
    elif primary_forward_return is not None:
        hit = primary_forward_return > Decimal("0")
    else:
        hit = None
    false_breakout = None
    if confirmation_level is not None and invalidation_level is not None and future_window:
        touched_confirmation = False
        false_breakout = False
        for candle in future_window:
            if candle.close >= confirmation_level:
                touched_confirmation = True
            if touched_confirmation and candle.close <= invalidation_level:
                false_breakout = True
                break
    max_adverse_excursion = None
    if future_window:
        worst_low = min(candle.low for candle in future_window)
        max_adverse_excursion = _rate_of_return(entry.close, worst_low)

    return SetupReplayObservation(
        signal_index=signal_index,
        observed_at=entry.timestamp,
        entry_close=entry.close,
        forward_returns_by_horizon=forward_returns,
        hit=hit,
        false_breakout=false_breakout,
        max_adverse_excursion=max_adverse_excursion,
    )


def _build_walk_forward_windows(
    *,
    observations: Sequence[SetupReplayObservation],
    horizons: tuple[int, ...],
    window_size: int | None,
) -> tuple[SetupReplayWalkForwardWindow, ...]:
    if window_size is None:
        window_size = len(observations)
    if window_size <= 0:
        raise ValueError("walk_forward_window_size must be a positive signal count")
    chronological_observations = tuple(
        sorted(observations, key=lambda observation: observation.observed_at)
    )
    windows: list[SetupReplayWalkForwardWindow] = []
    for window_index, start in enumerate(range(0, len(chronological_observations), window_size)):
        window_observations = tuple(chronological_observations[start : start + window_size])
        if not window_observations:
            continue
        metrics, _ = _aggregate_metrics(window_observations, horizons)
        windows.append(
            SetupReplayWalkForwardWindow(
                window_index=window_index,
                signal_indices=tuple(
                    observation.signal_index for observation in window_observations
                ),
                start_observed_at=window_observations[0].observed_at,
                end_observed_at=window_observations[-1].observed_at,
                sample_size=len(window_observations),
                evaluable_signals=sum(
                    1
                    for observation in window_observations
                    if any(
                        value is not None
                        for value in observation.forward_returns_by_horizon.values()
                    )
                ),
                metrics=metrics,
            )
        )
    return tuple(windows)


def _aggregate_metrics(
    observations: Sequence[SetupReplayObservation], horizons: tuple[int, ...]
) -> tuple[SetupReplayMetrics, tuple[str, ...]]:
    returns_by_horizon: dict[int, Decimal | None] = {}
    unavailable_windows = 0
    total_windows = len(observations) * len(horizons)
    for horizon in horizons:
        values: list[Decimal] = []
        for observation in observations:
            forward_return = observation.forward_returns_by_horizon[horizon]
            if forward_return is not None:
                values.append(forward_return)
        unavailable_windows += len(observations) - len(values)
        returns_by_horizon[horizon] = _average(values) if values else None

    hit_values = [observation.hit for observation in observations if observation.hit is not None]
    false_breakout_values = [
        observation.false_breakout
        for observation in observations
        if observation.false_breakout is not None
    ]
    adverse_values: list[Decimal] = []
    for observation in observations:
        if observation.max_adverse_excursion is not None:
            adverse_values.append(observation.max_adverse_excursion)
    unavailable_context: tuple[str, ...] = ()
    if unavailable_windows:
        unavailable_context = (
            f"{unavailable_windows} of {total_windows} signal/horizon windows were unavailable "
            "because the candle history ended before the horizon.",
        )
    metrics = SetupReplayMetrics(
        hit_rate=_boolean_rate(hit_values),
        average_forward_return_by_horizon=returns_by_horizon,
        false_breakout_rate=_boolean_rate(false_breakout_values),
        max_adverse_excursion=min(adverse_values) if adverse_values else None,
        event_usefulness=_event_usefulness(returns_by_horizon, hit_values, false_breakout_values),
        data_availability_rate=_quantize_ratio(total_windows - unavailable_windows, total_windows),
    )
    return metrics, unavailable_context


def _event_usefulness(
    returns_by_horizon: Mapping[int, Decimal | None],
    hit_values: Sequence[bool],
    false_breakout_values: Sequence[bool],
) -> Decimal | None:
    components = [value for value in returns_by_horizon.values() if value is not None]
    if hit_values:
        hit_rate = _boolean_rate(hit_values)
        if hit_rate is not None:
            components.append(hit_rate)
    if false_breakout_values:
        false_breakout_rate = _boolean_rate(false_breakout_values)
        if false_breakout_rate is not None:
            components.append(Decimal("1") - false_breakout_rate)
    return _average(components) if components else None


def _average(values: Sequence[Decimal]) -> Decimal:
    return _quantize_decimal(_average_raw(values), Decimal("0.0001"))


def _average_raw(values: Sequence[Decimal]) -> Decimal:
    materialized = tuple(values)
    return sum(materialized) / Decimal(len(materialized))


def _boolean_rate(values: Sequence[bool]) -> Decimal | None:
    if not values:
        return None
    return _quantize_ratio(sum(1 for value in values if value), len(values))


def _rate_of_return(entry: Decimal, exit_value: Decimal) -> Decimal:
    return _quantize_decimal((exit_value - entry) / entry, Decimal("0.0001"))


def _quantize_ratio(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal("0.00")
    return _quantize_decimal(Decimal(numerator) / Decimal(denominator), Decimal("0.01"))


def _quantize_decimal(value: Decimal, quantum: Decimal) -> Decimal:
    return value.quantize(quantum, rounding=ROUND_HALF_UP)
