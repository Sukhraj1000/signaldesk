from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from signaldesk_backend import (
    Candle,
    ProviderCapability,
    ProviderRegistry,
    ProviderResult,
    Quote,
    Symbol,
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

    assert registry.names() == ("local-fixture",)
    health = registry.get("local-fixture").health_check()
    assert health == ProviderResult.success(
        provider="local-fixture",
        data="ready (no external credentials required)",
    )
