from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from signaldesk_backend import Candle, Symbol
from signaldesk_backend.backtesting import (
    SetupReplayReport,
    evaluate_setup_replay,
)

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
