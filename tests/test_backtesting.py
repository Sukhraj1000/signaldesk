import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from signaldesk_backend import Candle, Symbol
from signaldesk_backend.backtesting import (
    SetupReplayReport,
    derive_setup_signal_indices,
    evaluate_setup_replay,
    supported_setup_labels,
)
from signaldesk_cli.main import _setup_replay_report_payload

BASE_TIME = datetime(2026, 1, 1, tzinfo=UTC)


def _candle(day: int, close: str, high: str | None = None, low: str | None = None) -> Candle:
    price = Decimal(close)
    return Candle(
        symbol=Symbol("AMD"),
        timestamp=BASE_TIME + timedelta(days=day),
        open=price,
        high=Decimal(high) if high is not None else price,
        low=Decimal(low) if low is not None else price,
        close=price,
        volume=1_000,
    )


def test_supported_setup_labels_are_canonical_and_discoverable() -> None:
    assert supported_setup_labels() == (
        "breakdown_watch",
        "breakout_watch",
        "moving_average_loss",
        "moving_average_reclaim",
        "relative_volume_spike",
    )


def test_derive_setup_signal_indices_finds_deterministic_builtin_labels() -> None:
    candles = (
        _candle(0, "10", high="11", low="9"),
        _candle(1, "10", high="11", low="9"),
        _candle(2, "10", high="11", low="9"),
        _candle(3, "12", high="12", low="10"),
        _candle(4, "8", high="9", low="8"),
    )

    assert derive_setup_signal_indices(
        setup_label="breakout-watch", candles=candles, lookback=3
    ) == (3,)
    assert derive_setup_signal_indices(
        setup_label="breakdown_watch", candles=candles, lookback=3
    ) == (4,)


def test_derive_setup_signal_indices_rejects_unknown_label_but_replay_allows_manual_labels() -> (
    None
):
    candles = (_candle(0, "100"), _candle(1, "101"))

    with pytest.raises(ValueError, match="unsupported setup_label"):
        derive_setup_signal_indices(setup_label="custom_label", candles=candles, lookback=1)

    report = evaluate_setup_replay(
        setup_label="custom label",
        candles=candles,
        signal_indices=(0,),
        horizons=(1,),
        generated_at=BASE_TIME,
    )

    assert report.setup_label == "custom_label"


def test_evaluate_setup_replay_reports_forward_returns_and_limits_scope() -> None:
    candles = (
        _candle(0, "100", high="101", low="99"),
        _candle(1, "102", high="103", low="98"),
        _candle(2, "105", high="106", low="101"),
        _candle(3, "99", high="100", low="96"),
        _candle(4, "110", high="111", low="104"),
    )

    report = evaluate_setup_replay(
        setup_label="breakout_watch",
        candles=candles,
        signal_indices=(0, 1),
        horizons=(1, 3),
        confirmation_level=Decimal("104"),
        invalidation_level=Decimal("97"),
        provider="fixture",
        source="unit-test-candles",
        generated_at=BASE_TIME,
        timeframe="1d",
    )

    assert isinstance(report, SetupReplayReport)
    assert report.setup_label == "breakout_watch"
    assert report.sample_size == 2
    assert report.evaluable_signals == 2
    assert report.metrics.hit_rate == Decimal("1.00")
    assert report.metrics.average_forward_return_by_horizon == {
        1: Decimal("0.0247"),
        3: Decimal("0.0342"),
    }
    assert report.metrics.false_breakout_rate == Decimal("0.00")
    assert report.metrics.max_adverse_excursion == Decimal("-0.0588")
    assert report.metrics.data_availability_rate == Decimal("1.00")
    assert report.limitations == (
        "Historical setup replay is deterministic research only; "
        "it is not live trading or broker execution.",
    )
    assert report.provenance.provider == "fixture"


def test_evaluate_setup_replay_marks_unavailable_forward_windows() -> None:
    candles = (_candle(0, "100"), _candle(1, "101"), _candle(2, "102"))

    report = evaluate_setup_replay(
        setup_label="breakout_watch",
        candles=candles,
        signal_indices=(1, 2),
        horizons=(1, 3),
        generated_at=BASE_TIME,
        timeframe="1d",
    )

    assert report.sample_size == 2
    assert report.evaluable_signals == 1
    assert report.metrics.data_availability_rate == Decimal("0.25")
    assert report.metrics.average_forward_return_by_horizon == {1: Decimal("0.0099"), 3: None}
    assert report.metrics.hit_rate == Decimal("1.00")
    assert report.unavailable_context == (
        "3 of 4 signal/horizon windows were unavailable because the candle history ended "
        "before the horizon.",
    )


def test_evaluate_setup_replay_reports_walk_forward_windows() -> None:
    candles = (
        _candle(0, "100"),
        _candle(1, "101"),
        _candle(2, "102"),
        _candle(3, "99"),
        _candle(4, "98"),
        _candle(5, "105"),
    )

    report = evaluate_setup_replay(
        setup_label="breakout_watch",
        candles=candles,
        signal_indices=(0, 1, 3, 4),
        horizons=(1,),
        walk_forward_window_size=2,
        generated_at=BASE_TIME,
    )

    assert [window.signal_indices for window in report.walk_forward_windows] == [(0, 1), (3, 4)]
    assert [window.sample_size for window in report.walk_forward_windows] == [2, 2]
    assert [window.evaluable_signals for window in report.walk_forward_windows] == [2, 2]
    assert [window.metrics.hit_rate for window in report.walk_forward_windows] == [
        Decimal("1.00"),
        Decimal("0.50"),
    ]
    assert report.walk_forward_windows[0].metrics.average_forward_return_by_horizon == {
        1: Decimal("0.0100")
    }

    payload = _setup_replay_report_payload(report)
    assert payload["walk_forward_windows"][0] == {
        "window_index": 0,
        "signal_indices": [0, 1],
        "start_observed_at": candles[0].timestamp.isoformat(),
        "end_observed_at": candles[1].timestamp.isoformat(),
        "sample_size": 2,
        "evaluable_signals": 2,
        "metrics": {
            "hit_rate": "1.00",
            "average_forward_return_by_horizon": {"1": "0.0100"},
            "false_breakout_rate": None,
            "max_adverse_excursion": "0.0099",
            "event_usefulness": "0.5050",
            "data_availability_rate": "1.00",
        },
    }


def test_walk_forward_windows_are_chronological_for_unsorted_signal_indices() -> None:
    candles = (
        _candle(0, "100"),
        _candle(1, "101"),
        _candle(2, "102"),
        _candle(3, "99"),
        _candle(4, "98"),
        _candle(5, "105"),
    )

    report = evaluate_setup_replay(
        setup_label="breakout_watch",
        candles=candles,
        signal_indices=(4, 0, 3, 1),
        horizons=(1,),
        walk_forward_window_size=2,
        generated_at=BASE_TIME,
    )

    assert [window.signal_indices for window in report.walk_forward_windows] == [(0, 1), (3, 4)]
    assert report.walk_forward_windows[0].start_observed_at == candles[0].timestamp
    assert report.walk_forward_windows[0].end_observed_at == candles[1].timestamp
    assert report.walk_forward_windows[1].start_observed_at == candles[3].timestamp
    assert report.walk_forward_windows[1].end_observed_at == candles[4].timestamp


def test_evaluate_setup_replay_defaults_generated_at_to_latest_candle_timestamp() -> None:
    candles = (_candle(0, "100"), _candle(1, "101"), _candle(2, "102"))

    first = evaluate_setup_replay(
        setup_label="breakout_watch",
        candles=candles,
        signal_indices=(0,),
        horizons=(1,),
    )
    second = evaluate_setup_replay(
        setup_label="breakout_watch",
        candles=candles,
        signal_indices=(0,),
        horizons=(1,),
    )

    assert first.provenance.generated_at == candles[-1].timestamp
    assert second.provenance.generated_at == first.provenance.generated_at


def test_evaluate_setup_replay_bounds_outcome_checks_to_max_horizon() -> None:
    candles = (
        _candle(0, "100", low="100"),
        _candle(1, "99", low="98"),
        _candle(2, "99", low="97"),
        _candle(3, "110", low="50"),
        _candle(4, "80", low="80"),
    )

    report = evaluate_setup_replay(
        setup_label="breakout_watch",
        candles=candles,
        signal_indices=(0,),
        horizons=(1, 2),
        confirmation_level=Decimal("105"),
        invalidation_level=Decimal("90"),
        generated_at=BASE_TIME,
    )

    observation = report.observations[0]
    assert observation.hit is False
    assert observation.false_breakout is False
    assert observation.max_adverse_excursion == Decimal("-0.0300")


def test_evaluate_setup_replay_rejects_ambiguous_or_execution_like_inputs() -> None:
    candles = (_candle(0, "100"), _candle(1, "101"))

    with pytest.raises(ValueError, match="broker"):
        evaluate_setup_replay(
            setup_label="breakout_watch",
            candles=candles,
            signal_indices=(0,),
            broker="paper",
        )
    with pytest.raises(ValueError, match="horizons"):
        evaluate_setup_replay(
            setup_label="breakout_watch",
            candles=candles,
            signal_indices=(0,),
            horizons=(0,),
        )
    with pytest.raises(ValueError, match="same symbol"):
        evaluate_setup_replay(
            setup_label="breakout_watch",
            candles=(candles[0], _candle(1, "101")),
            signal_indices=(0,),
            symbol=Symbol("NVDA"),
        )


def test_setup_replay_json_schema_documents_cli_payload_contract() -> None:
    candles = (_candle(0, "100"), _candle(1, "101"), _candle(2, "102"))
    report = evaluate_setup_replay(
        setup_label="breakout_watch",
        candles=candles,
        signal_indices=(0, 1),
        horizons=(1,),
        generated_at=BASE_TIME,
        timeframe="1d",
    )

    payload = _setup_replay_report_payload(report)
    schema_path = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "schemas"
        / "signaldesk.backtest.setup_replay.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    metrics_schema_ref = schema["properties"]["metrics"]["$ref"]
    metrics_schema = schema["$defs"][metrics_schema_ref.rsplit("/", 1)[-1]]

    assert payload["schema_version"] == schema["properties"]["schema_version"]["const"]
    assert set(schema["required"]) == set(payload)
    assert set(metrics_schema["required"]) == set(payload["metrics"])
    assert set(schema["properties"]["provenance"]["required"]) == set(payload["provenance"])
    forbidden_execution_fields = {"broker", "order", "fill", "position_size", "slippage"}
    assert forbidden_execution_fields.isdisjoint(schema["properties"])
    assert schema["additionalProperties"] is False
    assert payload["limitations"]
