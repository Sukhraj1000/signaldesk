from datetime import UTC, datetime
from decimal import Decimal

import pytest
from signaldesk_backend import Candle, ProviderCapability, ProviderResult, Quote, Symbol

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
