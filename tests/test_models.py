from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from signaldesk_backend import (
    Candle,
    KeyLevels,
    Provenance,
    ProviderCapability,
    ProviderResult,
    Quote,
    SignalCard,
    Symbol,
    TechnicalEvent,
    TechnicalSnapshot,
)

NOW = datetime(2026, 1, 15, 14, 30, tzinfo=UTC)


def test_symbol_normalizes_ticker_and_defaults() -> None:
    symbol = Symbol(" amd ")

    assert symbol.ticker == "AMD"
    assert symbol.asset_class == "equity"
    assert symbol.currency == "USD"


@pytest.mark.parametrize("ticker", ["", "   ", "BRK B"])
def test_symbol_rejects_empty_or_space_separated_tickers(ticker: str) -> None:
    with pytest.raises(ValueError, match="ticker"):
        Symbol(ticker)


@pytest.mark.parametrize("field_name", ["asset_class", "currency"])
def test_symbol_rejects_blank_metadata(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        Symbol("AMD", **{field_name: " "})


def test_candle_accepts_valid_ohlcv_data() -> None:
    candle = Candle(
        symbol=Symbol("AMD"),
        timestamp=NOW,
        open=Decimal("100.00"),
        high=Decimal("105.50"),
        low=Decimal("99.25"),
        close=Decimal("102.75"),
        volume=1_000_000,
    )

    assert candle.symbol.ticker == "AMD"
    assert candle.high == Decimal("105.50")
    assert candle.volume == 1_000_000


def test_candle_rejects_invalid_price_range() -> None:
    with pytest.raises(ValueError, match="high"):
        Candle(
            symbol=Symbol("AMD"),
            timestamp=NOW,
            open=Decimal("100"),
            high=Decimal("99"),
            low=Decimal("98"),
            close=Decimal("100"),
            volume=100,
        )


@pytest.mark.parametrize("volume", [-1, -100])
def test_candle_rejects_negative_volume(volume: int) -> None:
    with pytest.raises(ValueError, match="volume"):
        Candle(
            symbol=Symbol("AMD"),
            timestamp=NOW,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=volume,
        )


def test_quote_accepts_bid_ask_last_snapshot() -> None:
    quote = Quote(
        symbol=Symbol("msft"),
        timestamp=NOW,
        bid=Decimal("420.10"),
        ask=Decimal("420.15"),
        last=Decimal("420.12"),
    )

    assert quote.symbol.ticker == "MSFT"
    assert quote.ask == Decimal("420.15")


def test_quote_rejects_crossed_bid_ask() -> None:
    with pytest.raises(ValueError, match="ask"):
        Quote(
            symbol=Symbol("MSFT"),
            timestamp=NOW,
            bid=Decimal("420.20"),
            ask=Decimal("420.10"),
            last=Decimal("420.12"),
        )


def test_provider_capability_records_supported_features() -> None:
    capability = ProviderCapability(
        provider="yfinance",
        supports_realtime=False,
        supports_historical=True,
        supported_asset_classes=frozenset({"equity", "etf"}),
        max_history_days=3650,
        rate_limit_per_minute=None,
    )

    assert capability.provider == "yfinance"
    assert capability.supports_historical is True
    assert "equity" in capability.supported_asset_classes


def test_provider_result_success_and_failure_shapes() -> None:
    candle = Candle(
        symbol=Symbol("AMD"),
        timestamp=NOW,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100.50"),
        volume=100,
    )

    success = ProviderResult.success(provider="stub", data=candle, warnings=("delayed",))
    failure: ProviderResult[str] = ProviderResult.failure(provider="stub", error="not available")

    assert success.ok is True
    assert success.data == candle
    assert success.warnings == ("delayed",)
    assert failure.ok is False
    assert failure.error == "not available"


def test_provider_result_rejects_ambiguous_data_and_error() -> None:
    with pytest.raises(ValueError, match="either data or error"):
        ProviderResult(provider="stub", data="payload", error="failed")


def _analysis_fixture() -> tuple[Provenance, KeyLevels, TechnicalEvent, TechnicalSnapshot]:
    provenance = Provenance(
        provider="fixture",
        source="unit-test-candles",
        generated_at=NOW,
        timeframe="1d",
        inputs=("AMD", "  close  "),
    )
    levels = KeyLevels(
        support=(Decimal("100"), Decimal("95.50")),
        resistance=(Decimal("110"),),
        confirmation=Decimal("111"),
        invalidation=Decimal("94"),
    )
    event = TechnicalEvent(
        event_type="Breakout",
        observed_at=NOW,
        summary="Closed above resistance",
        price=Decimal("112"),
        severity="bullish",
    )
    snapshot = TechnicalSnapshot(
        symbol=Symbol("amd"),
        as_of=NOW,
        timeframe="1d",
        trend="UP",
        last_price=Decimal("112"),
        key_levels=levels,
        events=(event,),
        provenance=provenance,
        indicators={" RSI ": Decimal("62.5")},
    )
    return provenance, levels, event, snapshot


def test_analysis_models_construct_and_normalize_values() -> None:
    provenance, levels, event, snapshot = _analysis_fixture()

    assert provenance.inputs == ("AMD", "close")
    assert levels.support == (Decimal("100"), Decimal("95.50"))
    assert event.event_type == "breakout"
    assert snapshot.symbol.ticker == "AMD"
    assert snapshot.trend == "up"
    assert snapshot.indicators == {"rsi": Decimal("62.5")}


def test_signal_card_references_analysis_facts_without_credentials() -> None:
    provenance, levels, event, snapshot = _analysis_fixture()

    card = SignalCard(
        symbol=Symbol("AMD"),
        generated_at=NOW,
        timeframe="1d",
        bias="Watch",
        summary="Watch for continuation above confirmation with invalidation below support.",
        confidence=Decimal("0.70"),
        snapshot=snapshot,
        key_levels=levels,
        events=(event,),
        provenance=(provenance,),
        tags=(" Breakout ", "Momentum"),
    )

    assert card.bias == "watch"
    assert card.snapshot == snapshot
    assert card.key_levels == levels
    assert card.events == (event,)
    assert card.provenance == (provenance,)
    assert card.tags == ("breakout", "momentum")


def test_analysis_models_serialize_with_dataclass_payloads() -> None:
    provenance, levels, event, snapshot = _analysis_fixture()
    card = SignalCard(
        symbol=Symbol("AMD"),
        generated_at=NOW,
        timeframe="1d",
        bias="neutral",
        summary="Facts-only summary.",
        confidence=Decimal("0.50"),
        snapshot=snapshot,
        key_levels=levels,
        events=(event,),
        provenance=(provenance,),
    )

    provenance_payload = asdict(provenance)
    reconstructed_provenance = Provenance(**provenance_payload)
    card_payload = asdict(card)

    assert reconstructed_provenance == provenance
    assert card_payload["symbol"]["ticker"] == "AMD"
    assert card_payload["snapshot"]["key_levels"]["confirmation"] == Decimal("111")
    assert card_payload["provenance"][0]["source"] == "unit-test-candles"


@pytest.mark.parametrize(
    ("factory", "match"),
    [
        (
            lambda: Provenance(
                provider=" ", source="fixture", generated_at=NOW, timeframe="1d"
            ),
            "provider",
        ),
        (lambda: KeyLevels(support=(Decimal("0"),)), "support"),
        (
            lambda: TechnicalEvent(
                event_type="breakout", observed_at=NOW, summary=" ", severity="info"
            ),
            "summary",
        ),
        (
            lambda: TechnicalSnapshot(
                symbol=Symbol("AMD"),
                as_of=NOW,
                timeframe="1d",
                trend="maybe",
                last_price=Decimal("100"),
                key_levels=KeyLevels(support=(Decimal("90"),)),
            ),
            "trend",
        ),
        (
            lambda: TechnicalSnapshot(
                symbol=Symbol("AMD"),
                as_of=NOW,
                timeframe="1d",
                trend="up",
                last_price=Decimal("100"),
                key_levels=KeyLevels(support=(Decimal("90"),)),
                indicators={"RSI": Decimal("60"), " rsi ": Decimal("61")},
            ),
            "indicator names collide",
        ),
        (
            lambda: SignalCard(
                symbol=Symbol("AMD"),
                generated_at=NOW,
                timeframe="1d",
                bias="watch",
                summary="facts",
                confidence=Decimal("1.1"),
            ),
            "confidence",
        ),
        (
            lambda: SignalCard(
                symbol=Symbol("AMD"),
                generated_at=NOW,
                timeframe="1d",
                bias="watch",
                summary="facts",
                confidence=1,  # type: ignore[arg-type]
            ),
            "confidence must be a Decimal",
        ),
    ],
)
def test_analysis_models_reject_invalid_values(
    factory: Callable[[], object], match: str
) -> None:
    with pytest.raises((TypeError, ValueError), match=match):
        factory()
