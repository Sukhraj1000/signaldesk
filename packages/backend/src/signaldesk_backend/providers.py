"""Provider contracts and registry for market-data adapters."""

from collections.abc import Iterable
from datetime import datetime
from typing import Protocol

from signaldesk_backend.models import Candle, ProviderCapability, ProviderResult, Quote, Symbol


def normalize_provider_name(name: str) -> str:
    """Return the canonical registry key for a provider name."""

    normalized = name.strip().lower()
    if not normalized:
        raise ValueError("provider name is required")
    return normalized


class MarketDataProvider(Protocol):
    """Typed contract for provider-agnostic market data retrieval."""

    @property
    def name(self) -> str:
        """Human-readable provider name used as the registry key."""
        ...

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        """Return the provider's declared market-data capabilities."""
        ...

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        """Fetch historical OHLCV candles for a symbol and interval."""
        ...

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        """Fetch a point-in-time quote for a symbol."""
        ...

    def health_check(self) -> ProviderResult[str]:
        """Return a lightweight provider health status without exposing secrets."""
        ...


class ProviderRegistry:
    """Deterministic registry for named market-data providers."""

    def __init__(self, providers: Iterable[MarketDataProvider] = ()) -> None:
        self._providers: dict[str, MarketDataProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: MarketDataProvider) -> None:
        """Register a provider by normalized name."""

        normalized_name = normalize_provider_name(provider.name)
        if normalized_name in self._providers:
            raise ValueError(f"provider already registered: {normalized_name}")
        self._providers[normalized_name] = provider

    def get(self, name: str) -> MarketDataProvider:
        """Return a registered provider by normalized name."""

        normalized_name = normalize_provider_name(name)
        try:
            return self._providers[normalized_name]
        except KeyError as exc:
            raise KeyError(f"provider not registered: {normalized_name}") from exc

    def names(self) -> tuple[str, ...]:
        """Return registered provider names in deterministic order."""

        return tuple(sorted(self._providers))

    def list(self) -> tuple[MarketDataProvider, ...]:
        """Return registered providers sorted by normalized name."""

        return tuple(self._providers[name] for name in self.names())

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        try:
            normalized_name = normalize_provider_name(name)
        except ValueError:
            return False
        return normalized_name in self._providers

    def __len__(self) -> int:
        return len(self._providers)
