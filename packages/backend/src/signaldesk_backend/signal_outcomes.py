"""Deterministic forward outcome evaluation for saved signal-history records.

This module compares archived SignalDesk signal-history records with later
candles. It is provider-agnostic decision-support research only: it does not
model orders, fills, broker execution, position sizing, slippage, or advice.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from signaldesk_backend.models import SIGNAL_HISTORY_SCHEMA_VERSION, Candle, Symbol

SIGNAL_OUTCOME_EVALUATION_SCHEMA_VERSION = "signaldesk.signal_outcome_evaluation.v1"
_OUTCOME_LIMITATION = (
    "Forward outcome tracking is deterministic decision-support research only; "
    "it is not a recommendation, live trading, broker execution, or position sizing."
)


def evaluate_signal_history_outcome(
    *,
    history_record: Mapping[str, Any],
    candles: Sequence[Candle],
    horizons: Sequence[int] = (1, 5, 20),
    provider: str,
    generated_at: datetime,
) -> dict[str, Any]:
    """Evaluate one saved signal-history record against later candles."""

    validate_signal_history_record_payload(history_record)
    symbol = Symbol(str(_required(history_record, "symbol")))
    latest_timestamp = _parse_datetime(
        _required(history_record, "latest_timestamp"), "latest_timestamp"
    )
    latest_close = _parse_decimal(_required(history_record, "latest_close"), "latest_close")
    normalized_horizons = _normalize_horizons(horizons)
    normalized_candles = tuple(candles)
    for candle in normalized_candles:
        if candle.symbol != symbol:
            raise ValueError("all outcome candles must match the history record symbol")

    future_candles = tuple(
        sorted(
            (candle for candle in normalized_candles if candle.timestamp > latest_timestamp),
            key=lambda candle: candle.timestamp,
        )
    )
    returns_by_horizon: dict[str, str | None] = {}
    unavailable_context: list[dict[str, str | int]] = []
    for horizon in normalized_horizons:
        if len(future_candles) < horizon:
            returns_by_horizon[str(horizon)] = None
            unavailable_context.append(
                {
                    "context_type": "forward_outcome",
                    "reason": "forward candle horizon is not available yet",
                    "horizon": horizon,
                }
            )
        else:
            returns_by_horizon[str(horizon)] = str(
                _rate_of_return(latest_close, future_candles[horizon - 1].close)
            )

    confirmation_price = _level_price(history_record.get("confirmation_level"))
    invalidation_price = _level_price(history_record.get("invalidation_level"))
    confirmation_hit_at = _first_touch_timestamp(
        future_candles, confirmation_price, direction="above"
    )
    invalidation_hit_at = _first_touch_timestamp(
        future_candles, invalidation_price, direction="below"
    )
    if confirmation_price is None:
        unavailable_context.append(
            {
                "context_type": "confirmation_level",
                "reason": "history record did not include a deterministic confirmation level",
            }
        )
    if invalidation_price is None:
        unavailable_context.append(
            {
                "context_type": "invalidation_level",
                "reason": "history record did not include a deterministic invalidation level",
            }
        )

    evaluable_horizons = sum(value is not None for value in returns_by_horizon.values())
    return {
        "schema_version": SIGNAL_OUTCOME_EVALUATION_SCHEMA_VERSION,
        "source_schema_version": history_record.get("schema_version"),
        "run_id": history_record.get("run_id"),
        "symbol": symbol.ticker,
        "provider": provider,
        "interval": history_record.get("interval"),
        "generated_at": generated_at.isoformat(),
        "signal_observed_at": latest_timestamp.isoformat(),
        "signal_latest_close": str(latest_close),
        "signal_state": history_record.get("signal_state"),
        "momentum_state": history_record.get("momentum_state"),
        "horizons": list(normalized_horizons),
        "forward_returns_by_horizon": returns_by_horizon,
        "confirmation": {
            "level": None if confirmation_price is None else str(confirmation_price),
            "hit": confirmation_hit_at is not None,
            "hit_at": None if confirmation_hit_at is None else confirmation_hit_at.isoformat(),
        },
        "invalidation": {
            "level": None if invalidation_price is None else str(invalidation_price),
            "hit": invalidation_hit_at is not None,
            "hit_at": None if invalidation_hit_at is None else invalidation_hit_at.isoformat(),
        },
        "coverage": {
            "available_forward_candles": len(future_candles),
            "evaluable_horizons": evaluable_horizons,
            "requested_horizons": len(normalized_horizons),
            "data_availability_rate": str(_ratio(evaluable_horizons, len(normalized_horizons))),
        },
        "unavailable_context": unavailable_context,
        "limitations": [_OUTCOME_LIMITATION],
        "decision_support_only": True,
    }


def validate_signal_history_record_payload(history_record: Mapping[str, Any]) -> None:
    """Validate the small subset required for deterministic outcome evaluation."""

    if history_record.get("schema_version") != SIGNAL_HISTORY_SCHEMA_VERSION:
        raise ValueError(f"signal history schema_version must be {SIGNAL_HISTORY_SCHEMA_VERSION}")
    for field_name in (
        "run_id",
        "symbol",
        "provider",
        "interval",
        "latest_timestamp",
        "latest_close",
        "signal_state",
        "momentum_state",
    ):
        _required(history_record, field_name)
    _parse_datetime(history_record["latest_timestamp"], "latest_timestamp")
    _parse_decimal(history_record["latest_close"], "latest_close")


def _required(payload: Mapping[str, Any], field_name: str) -> Any:
    value = payload.get(field_name)
    if value is None or (isinstance(value, str) and not value.strip()):
        raise ValueError(f"signal history {field_name} is required")
    return value


def _parse_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"signal history {field_name} must be an ISO datetime string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"signal history {field_name} must be timezone-aware")
    return parsed


def _parse_decimal(value: Any, field_name: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"signal history {field_name} must be a decimal") from exc
    if not parsed.is_finite() or parsed <= Decimal("0"):
        raise ValueError(f"signal history {field_name} must be a positive decimal")
    return parsed


def _normalize_horizons(horizons: Sequence[int]) -> tuple[int, ...]:
    normalized = tuple(sorted(set(horizons)))
    if not normalized or any(horizon <= 0 for horizon in normalized):
        raise ValueError("horizons must include positive forward candle counts")
    return normalized


def _level_price(value: Any) -> Decimal | None:
    if not isinstance(value, Mapping):
        return None
    raw_price = value.get("price")
    if raw_price is None:
        return None
    return _parse_decimal(raw_price, "level price")


def _first_touch_timestamp(
    candles: Sequence[Candle], price: Decimal | None, *, direction: str
) -> datetime | None:
    if price is None:
        return None
    for candle in candles:
        if direction == "above" and candle.high >= price:
            return candle.timestamp
        if direction == "below" and candle.low <= price:
            return candle.timestamp
    return None


def _rate_of_return(entry: Decimal, exit_value: Decimal) -> Decimal:
    return ((exit_value - entry) / entry).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _ratio(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal("0.00")
    return (Decimal(numerator) / Decimal(denominator)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
