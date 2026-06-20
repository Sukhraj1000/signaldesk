from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest
import signaldesk_backend.providers as providers_module
from signaldesk_backend import (
    Candle,
    ProviderCapability,
    ProviderRegistry,
    ProviderResult,
    Quote,
    Symbol,
    YFinanceProvider,
    default_provider_registry,
    normalize_provider_name,
)

NOW = datetime(2026, 1, 15, 14, 30, tzinfo=UTC)


@dataclass(frozen=True)
class FakeProvider:
    name: str

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        return (
            ProviderCapability(
                provider=self.name,
                supports_realtime=True,
                supports_historical=True,
                supported_asset_classes=frozenset({"equity"}),
                max_history_days=30,
            ),
        )

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        if start > end:
            return ProviderResult.failure(provider=self.name, error="start must be before end")
        if not interval.strip():
            return ProviderResult.failure(provider=self.name, error="interval is required")
        candle = Candle(
            symbol=symbol,
            timestamp=start,
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100.50"),
            volume=100,
        )
        return ProviderResult.success(provider=self.name, data=(candle,))

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        quote = Quote(symbol=symbol, timestamp=NOW, last=Decimal("100.50"))
        return ProviderResult.success(provider=self.name, data=quote)

    def health_check(self) -> ProviderResult[str]:
        return ProviderResult.success(provider=self.name, data="healthy")


class FakeHistory:
    empty = False

    def iterrows(self) -> tuple[tuple[datetime, dict[str, float]], ...]:
        return (
            (
                NOW,
                {
                    "Open": 100.0,
                    "High": 102.0,
                    "Low": 99.0,
                    "Close": 101.5,
                    "Volume": 12345.0,
                },
            ),
        )


class EmptyHistory(FakeHistory):
    empty = True


class FakeYFinanceTicker:
    def __init__(self, ticker: str) -> None:
        self.ticker = ticker
        self.fast_info = {"last_price": 101.5, "bid": 101.0, "ask": 102.0}
        self.info: dict[str, float] = {}

    def history(self, *, start: datetime, end: datetime, interval: str) -> FakeHistory:
        return FakeHistory()


class EmptyYFinanceTicker(FakeYFinanceTicker):
    fast_info: dict[str, float] = {}

    def __init__(self, ticker: str) -> None:
        self.ticker = ticker
        self.fast_info = {}
        self.info = {}

    def history(self, *, start: datetime, end: datetime, interval: str) -> EmptyHistory:
        return EmptyHistory()


class ExplodingYFinanceTicker(FakeYFinanceTicker):
    def history(self, *, start: datetime, end: datetime, interval: str) -> FakeHistory:
        raise RuntimeError("network failure detail")


class FakeYFinanceModule:
    def Ticker(self, ticker: str) -> FakeYFinanceTicker:
        return FakeYFinanceTicker(ticker)


class EmptyYFinanceModule:
    def Ticker(self, ticker: str) -> EmptyYFinanceTicker:
        return EmptyYFinanceTicker(ticker)


class ExplodingYFinanceModule:
    def Ticker(self, ticker: str) -> ExplodingYFinanceTicker:
        return ExplodingYFinanceTicker(ticker)


def test_normalize_provider_name_canonicalizes_registry_keys() -> None:
    assert normalize_provider_name("  Fixture Provider  ") == "fixture provider"


@pytest.mark.parametrize("name", ["", "   "])
def test_normalize_provider_name_rejects_blank_names(name: str) -> None:
    with pytest.raises(ValueError, match="provider name"):
        normalize_provider_name(name)


def test_provider_registry_registers_lists_and_retrieves_by_normalized_name() -> None:
    first = FakeProvider("Fixture")
    second = FakeProvider("alpha")
    registry = ProviderRegistry((first, second))

    assert len(registry) == 2
    assert registry.names() == ("alpha", "fixture")
    assert registry.list() == (second, first)
    assert registry.get(" FIXTURE ") is first
    assert "fixture" in registry


def test_provider_registry_rejects_duplicate_normalized_names() -> None:
    registry = ProviderRegistry((FakeProvider("fixture"),))

    with pytest.raises(ValueError, match="already registered: fixture"):
        registry.register(FakeProvider(" FIXTURE "))


def test_provider_registry_rejects_blank_provider_names() -> None:
    registry = ProviderRegistry()

    with pytest.raises(ValueError, match="provider name"):
        registry.register(FakeProvider(" "))


def test_provider_registry_reports_missing_provider_with_normalized_name() -> None:
    registry = ProviderRegistry()

    with pytest.raises(KeyError, match="missing"):
        registry.get("Missing")


def test_fake_provider_satisfies_interface_result_shapes() -> None:
    provider = FakeProvider("fixture")
    symbol = Symbol("amd")

    capabilities = provider.capabilities()
    candles = provider.get_historical_candles(
        symbol,
        start=NOW,
        end=NOW,
        interval="1d",
    )
    quote = provider.get_quote(symbol)
    health = provider.health_check()

    assert capabilities[0].provider == "fixture"
    assert capabilities[0].supports_historical is True
    assert candles.ok is True
    assert candles.data is not None
    assert candles.data[0].symbol == symbol
    assert quote.ok is True
    assert quote.data is not None
    assert quote.data.last == Decimal("100.50")
    assert health == ProviderResult.success(provider="fixture", data="healthy")


def test_default_provider_registry_includes_safe_local_fixture_provider() -> None:
    registry = default_provider_registry()

    assert registry.names() == ("local-fixture", "yfinance")
    health = registry.get("local-fixture").health_check()
    assert health == ProviderResult.success(
        provider="local-fixture",
        data="ready (no external credentials required)",
    )


def test_yfinance_provider_reports_capabilities_without_importing_dependency() -> None:
    provider = YFinanceProvider(_module=None)

    capabilities = provider.capabilities()

    assert capabilities[0].provider == "yfinance"
    assert capabilities[0].supports_realtime is True
    assert capabilities[0].supports_historical is True
    assert "equity" in capabilities[0].supported_asset_classes


def test_yfinance_provider_translates_history_and_quote_models() -> None:
    provider = YFinanceProvider(_module=FakeYFinanceModule())
    symbol = Symbol("amd")

    candles = provider.get_historical_candles(symbol, start=NOW, end=NOW, interval="1d")
    quote = provider.get_quote(symbol)

    assert candles.ok is True
    assert candles.data is not None
    assert candles.data == (
        Candle(
            symbol=symbol,
            timestamp=NOW,
            open=Decimal("100.0"),
            high=Decimal("102.0"),
            low=Decimal("99.0"),
            close=Decimal("101.5"),
            volume=12345,
        ),
    )
    assert quote.ok is True
    assert quote.data is not None
    assert quote.data.symbol == symbol
    assert quote.data.bid == Decimal("101.0")
    assert quote.data.ask == Decimal("102.0")
    assert quote.data.last == Decimal("101.5")


def test_yfinance_provider_handles_missing_dependency_without_crashing_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_import(module_name: str) -> None:
        raise ImportError(module_name)

    monkeypatch.setattr(providers_module, "import_module", fail_import)
    provider = YFinanceProvider(_module=None)

    result = provider.get_quote(Symbol("missing"))
    health = provider.health_check()

    assert result == ProviderResult.failure(
        provider="yfinance",
        error="optional dependency yfinance is not installed",
    )
    assert health == ProviderResult.success(
        provider="yfinance",
        data="unavailable until optional dependency yfinance is installed",
    )


def test_yfinance_provider_handles_empty_data_deterministically() -> None:
    provider = YFinanceProvider(_module=EmptyYFinanceModule())
    symbol = Symbol("unknown")

    candles = provider.get_historical_candles(symbol, start=NOW, end=NOW, interval="1d")
    quote = provider.get_quote(symbol)

    assert candles == ProviderResult.failure(
        provider="yfinance",
        error="no historical data for UNKNOWN",
    )
    assert quote == ProviderResult.failure(provider="yfinance", error="no quote data for UNKNOWN")


def test_yfinance_provider_sanitizes_provider_failures() -> None:
    provider = YFinanceProvider(_module=ExplodingYFinanceModule())

    result = provider.get_historical_candles(Symbol("amd"), start=NOW, end=NOW, interval="1d")

    assert result == ProviderResult.failure(
        provider="yfinance",
        error="yfinance historical fetch failed",
    )
    assert "network failure" not in (result.error or "")
