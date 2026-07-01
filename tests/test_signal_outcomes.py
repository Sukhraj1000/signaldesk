from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from signaldesk_backend import Candle, Symbol, evaluate_signal_history_outcome


def _record() -> dict[str, object]:
    return {
        "schema_version": "signaldesk.signal_history.v1",
        "run_id": "run-1",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "symbol": "AMD",
        "provider": "local-fixture",
        "provider_mode": "default",
        "interval": "1d",
        "requested_days": 20,
        "candle_count": 20,
        "latest_timestamp": "2026-01-10T00:00:00+00:00",
        "latest_close": "100",
        "signal_state": "improving",
        "momentum_state": "confirmed",
        "strength_score": "0.7",
        "risk_score": "0.2",
        "confirmation_level": {"price": "104", "kind": "resistance"},
        "invalidation_level": {"price": "97", "kind": "support"},
        "classification_reasons": ["fixture"],
        "unavailable_context": [],
    }


def _candle(day: int, close: str, high: str | None = None, low: str | None = None) -> Candle:
    price = Decimal(close)
    return Candle(
        symbol=Symbol("AMD"),
        timestamp=datetime(2026, 1, 10, tzinfo=UTC) + timedelta(days=day),
        open=price,
        high=Decimal(high) if high is not None else price,
        low=Decimal(low) if low is not None else price,
        close=price,
        volume=1000,
    )


def test_evaluate_signal_history_outcome_tracks_forward_returns_and_levels() -> None:
    payload = evaluate_signal_history_outcome(
        history_record=_record(),
        candles=(_candle(0, "100"), _candle(1, "103", high="105"), _candle(2, "96", low="96")),
        horizons=(1, 2),
        provider="local-fixture",
        generated_at=datetime(2026, 1, 13, tzinfo=UTC),
    )

    assert payload["schema_version"] == "signaldesk.signal_outcome_evaluation.v1"
    assert payload["decision_support_only"] is True
    assert payload["forward_returns_by_horizon"] == {"1": "0.0300", "2": "-0.0400"}
    assert payload["confirmation"] == {
        "level": "104",
        "hit": True,
        "hit_at": "2026-01-11T00:00:00+00:00",
    }
    assert payload["invalidation"] == {
        "level": "97",
        "hit": True,
        "hit_at": "2026-01-12T00:00:00+00:00",
    }
    assert payload["coverage"]["data_availability_rate"] == "1.00"
    assert payload["unavailable_context"] == []


def test_evaluate_signal_history_outcome_sorts_future_candles_and_partial_coverage() -> None:
    payload = evaluate_signal_history_outcome(
        history_record=_record(),
        candles=(
            _candle(2, "110", high="110"),
            _candle(0, "100"),
            _candle(1, "103", high="105"),
        ),
        horizons=(1, 5),
        provider="local-fixture",
        generated_at=datetime(2026, 1, 13, tzinfo=UTC),
    )

    assert payload["forward_returns_by_horizon"] == {"1": "0.0300", "5": None}
    assert payload["confirmation"]["hit_at"] == "2026-01-11T00:00:00+00:00"
    assert payload["coverage"]["data_availability_rate"] == "0.50"
    assert payload["unavailable_context"] == [
        {
            "context_type": "forward_outcome",
            "reason": "forward candle horizon is not available yet",
            "horizon": 5,
        }
    ]


def test_evaluate_signal_history_outcome_reports_missing_forward_context() -> None:
    record = _record()
    record["confirmation_level"] = None
    payload = evaluate_signal_history_outcome(
        history_record=record,
        candles=(_candle(0, "100"),),
        horizons=(1, 5),
        provider="local-fixture",
        generated_at=datetime(2026, 1, 13, tzinfo=UTC),
    )

    assert payload["forward_returns_by_horizon"] == {"1": None, "5": None}
    assert payload["coverage"]["data_availability_rate"] == "0.00"
    assert {item["context_type"] for item in payload["unavailable_context"]} == {
        "forward_outcome",
        "confirmation_level",
    }


def test_evaluate_signal_history_outcome_rejects_wrong_schema() -> None:
    record = _record()
    record["schema_version"] = "wrong"
    with pytest.raises(ValueError, match="schema_version"):
        evaluate_signal_history_outcome(
            history_record=record,
            candles=(_candle(1, "101"),),
            provider="local-fixture",
            generated_at=datetime(2026, 1, 13, tzinfo=UTC),
        )
