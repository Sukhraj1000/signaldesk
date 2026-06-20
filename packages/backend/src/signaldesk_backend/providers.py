"""Provider contracts, adapters, and registry for market-data providers."""

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from importlib import import_module
from typing import Any, Protocol, cast

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


@dataclass(frozen=True)
class LocalFixtureProvider:
    """Built-in provider used for local health checks before adapters exist."""

    name: str = "local-fixture"

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        """Return safe local-only capabilities for CLI discovery."""

        return (
            ProviderCapability(
                provider=self.name,
                supports_realtime=False,
                supports_historical=False,
                supported_asset_classes=frozenset({"fixture"}),
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
        """Report that the fixture provider does not serve market data."""

        return ProviderResult.failure(
            provider=self.name,
            error="local fixture provider does not serve historical market data",
        )

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        """Report that the fixture provider does not serve market data."""

        return ProviderResult.failure(
            provider=self.name,
            error="local fixture provider does not serve quotes",
        )

    def health_check(self) -> ProviderResult[str]:
        """Return a deterministic no-secret health status."""

        return ProviderResult.success(
            provider=self.name,
            data="ready (no external credentials required)",
        )


@dataclass(frozen=True)
class YFinanceProvider:
    """Optional yfinance-backed market-data provider adapter."""

    name: str = "yfinance"
    _module: Any | None = field(default=None, repr=False, compare=False)

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        """Return yfinance quote and candle capabilities without importing the package."""

        return (
            ProviderCapability(
                provider=self.name,
                supports_realtime=True,
                supports_historical=True,
                supported_asset_classes=frozenset({"equity", "etf", "crypto", "index"}),
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
        """Fetch historical candles via yfinance and translate them to domain models."""

        module_result = self._load_module()
        if not module_result.ok:
            return ProviderResult.failure(
                provider=self.name, error=module_result.error or "unavailable"
            )
        if start > end:
            return ProviderResult.failure(provider=self.name, error="start must be before end")
        normalized_interval = interval.strip()
        if not normalized_interval:
            return ProviderResult.failure(provider=self.name, error="interval is required")

        module = module_result.data
        if module is None:
            return ProviderResult.failure(
                provider=self.name, error="optional dependency yfinance is not installed"
            )

        try:
            ticker = module.Ticker(symbol.ticker)
            history = ticker.history(start=start, end=end, interval=normalized_interval)
        except Exception:
            return ProviderResult.failure(
                provider=self.name, error="yfinance historical fetch failed"
            )

        if bool(getattr(history, "empty", False)):
            return ProviderResult.failure(
                provider=self.name, error=f"no historical data for {symbol.ticker}"
            )

        candles: list[Candle] = []
        try:
            for timestamp, row in history.iterrows():
                candle = self._row_to_candle(symbol, timestamp, row)
                if candle is not None:
                    candles.append(candle)
        except Exception:
            return ProviderResult.failure(
                provider=self.name, error="yfinance historical data was invalid"
            )

        if not candles:
            return ProviderResult.failure(
                provider=self.name, error=f"no usable historical data for {symbol.ticker}"
            )
        return ProviderResult.success(provider=self.name, data=tuple(candles))

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        """Fetch a quote via yfinance and translate it to a Quote model."""

        module_result = self._load_module()
        if not module_result.ok:
            return ProviderResult.failure(
                provider=self.name, error=module_result.error or "unavailable"
            )

        module = module_result.data
        if module is None:
            return ProviderResult.failure(
                provider=self.name, error="optional dependency yfinance is not installed"
            )

        try:
            ticker = module.Ticker(symbol.ticker)
            fast_info = getattr(ticker, "fast_info", {})
        except Exception:
            return ProviderResult.failure(provider=self.name, error="yfinance quote fetch failed")

        last = self._pick_decimal(fast_info, "last_price", "lastPrice", "regularMarketPrice")
        bid = self._pick_decimal(fast_info, "bid", "bidPrice")
        ask = self._pick_decimal(fast_info, "ask", "askPrice")
        if last is None or bid is None or ask is None:
            try:
                info = getattr(ticker, "info", {})
            except Exception:
                info = {}
            if last is None:
                last = self._pick_decimal(
                    info, "regularMarketPrice", "currentPrice", "previousClose"
                )
            if bid is None:
                bid = self._pick_decimal(info, "bid", "bidPrice")
            if ask is None:
                ask = self._pick_decimal(info, "ask", "askPrice")

        if last is None and bid is None and ask is None:
            return ProviderResult.failure(
                provider=self.name, error=f"no quote data for {symbol.ticker}"
            )

        try:
            quote = Quote(
                symbol=symbol,
                timestamp=datetime.now(UTC),
                bid=bid,
                ask=ask,
                last=last,
            )
        except ValueError:
            return ProviderResult.failure(
                provider=self.name, error="yfinance quote data was invalid"
            )
        return ProviderResult.success(provider=self.name, data=quote)

    def health_check(self) -> ProviderResult[str]:
        """Report whether the optional yfinance dependency can be imported."""

        module_result = self._load_module()
        if not module_result.ok:
            return ProviderResult.success(
                provider=self.name,
                data="unavailable until optional dependency yfinance is installed",
            )
        return ProviderResult.success(
            provider=self.name, data="ready (optional dependency installed)"
        )

    def _load_module(self) -> ProviderResult[Any]:
        if self._module is not None:
            return ProviderResult.success(provider=self.name, data=self._module)
        try:
            return ProviderResult.success(provider=self.name, data=import_module("yfinance"))
        except ImportError:
            return ProviderResult.failure(
                provider=self.name,
                error="optional dependency yfinance is not installed",
            )

    def _row_to_candle(self, symbol: Symbol, timestamp: object, row: object) -> Candle | None:
        open_price = self._decimal_from_value(self._get_row_value(row, "Open"))
        high = self._decimal_from_value(self._get_row_value(row, "High"))
        low = self._decimal_from_value(self._get_row_value(row, "Low"))
        close = self._decimal_from_value(self._get_row_value(row, "Close"))
        volume_value = self._get_row_value(row, "Volume")
        if open_price is None or high is None or low is None or close is None:
            return None
        volume_decimal = self._decimal_from_value(volume_value)
        volume = int(volume_decimal) if volume_decimal is not None else 0
        return Candle(
            symbol=symbol,
            timestamp=self._coerce_timestamp(timestamp),
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )

    def _coerce_timestamp(self, value: object) -> datetime:
        if isinstance(value, datetime):
            timestamp = value
        elif hasattr(value, "to_pydatetime"):
            timestamp = cast(Any, value).to_pydatetime()
        elif hasattr(value, "date"):
            timestamp = datetime.combine(cast(Any, value), time.min)
        else:
            raise ValueError("timestamp is not datetime-like")
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            return timestamp.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC)

    def _pick_decimal(self, mapping: object, *keys: str) -> Decimal | None:
        for key in keys:
            value = self._get_row_value(mapping, key)
            decimal_value = self._decimal_from_value(value)
            if decimal_value is not None:
                return decimal_value
        return None

    def _get_row_value(self, row: object, key: str) -> object:
        if isinstance(row, dict):
            return row.get(key)
        try:
            return row[key]  # type: ignore[index]
        except Exception:
            return None

    def _decimal_from_value(self, value: object) -> Decimal | None:
        if value is None or value == "":
            return None
        try:
            decimal_value = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        if not decimal_value.is_finite() or decimal_value <= Decimal("0"):
            return None
        return decimal_value


def default_provider_registry() -> ProviderRegistry:
    """Return the safe default provider registry for local CLI commands."""

    return ProviderRegistry((LocalFixtureProvider(), YFinanceProvider()))
