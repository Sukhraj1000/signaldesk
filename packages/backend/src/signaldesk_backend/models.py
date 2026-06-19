"""Deterministic domain models for market data and provider responses."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Self


def _require_timezone_aware(timestamp: datetime) -> None:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")


def _require_positive_decimal(value: Decimal, field_name: str) -> None:
    if value <= Decimal("0"):
        raise ValueError(f"{field_name} must be positive")


@dataclass(frozen=True)
class Symbol:
    """A normalized tradable instrument identifier."""

    ticker: str
    exchange: str | None = None
    asset_class: str = "equity"
    currency: str = "USD"

    def __post_init__(self) -> None:
        ticker = self.ticker.strip().upper()
        if not ticker:
            raise ValueError("ticker is required")
        if any(character.isspace() for character in ticker):
            raise ValueError("ticker must not contain whitespace")
        asset_class = self.asset_class.strip().lower()
        if not asset_class:
            raise ValueError("asset_class is required")
        currency = self.currency.strip().upper()
        if not currency:
            raise ValueError("currency is required")
        object.__setattr__(self, "ticker", ticker)
        object.__setattr__(self, "asset_class", asset_class)
        object.__setattr__(self, "currency", currency)
        if self.exchange is not None:
            exchange = self.exchange.strip().upper()
            object.__setattr__(self, "exchange", exchange or None)


@dataclass(frozen=True, kw_only=True)
class Candle:
    """A single OHLCV market-data candle."""

    symbol: Symbol
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int

    def __post_init__(self) -> None:
        _require_timezone_aware(self.timestamp)
        for field_name in ("open", "high", "low", "close"):
            _require_positive_decimal(getattr(self, field_name), field_name)
        if self.high < max(self.open, self.low, self.close):
            raise ValueError("high must be greater than or equal to open, low, and close")
        if self.low > min(self.open, self.high, self.close):
            raise ValueError("low must be less than or equal to open, high, and close")
        if self.volume < 0:
            raise ValueError("volume must be non-negative")


@dataclass(frozen=True, kw_only=True)
class Quote:
    """A point-in-time bid/ask/last quote snapshot."""

    symbol: Symbol
    timestamp: datetime
    bid: Decimal | None = None
    ask: Decimal | None = None
    last: Decimal | None = None

    def __post_init__(self) -> None:
        _require_timezone_aware(self.timestamp)
        if self.bid is None and self.ask is None and self.last is None:
            raise ValueError("quote must include at least one of bid, ask, or last")
        for field_name in ("bid", "ask", "last"):
            value = getattr(self, field_name)
            if value is not None:
                _require_positive_decimal(value, field_name)
        if self.bid is not None and self.ask is not None and self.ask < self.bid:
            raise ValueError("ask must be greater than or equal to bid")


@dataclass(frozen=True, kw_only=True)
class ProviderCapability:
    """Declared capabilities for a market-data provider."""

    provider: str
    supports_realtime: bool
    supports_historical: bool
    supported_asset_classes: frozenset[str] = field(default_factory=frozenset)
    max_history_days: int | None = None
    rate_limit_per_minute: int | None = None

    def __post_init__(self) -> None:
        provider = self.provider.strip()
        if not provider:
            raise ValueError("provider is required")
        object.__setattr__(self, "provider", provider)
        normalized_asset_classes = frozenset(
            asset_class.strip().lower()
            for asset_class in self.supported_asset_classes
            if asset_class.strip()
        )
        object.__setattr__(self, "supported_asset_classes", normalized_asset_classes)
        if self.max_history_days is not None and self.max_history_days <= 0:
            raise ValueError("max_history_days must be positive")
        if self.rate_limit_per_minute is not None and self.rate_limit_per_minute <= 0:
            raise ValueError("rate_limit_per_minute must be positive")


@dataclass(frozen=True, kw_only=True)
class ProviderResult[T]:
    """A deterministic wrapper for provider success, warnings, or failure."""

    provider: str
    data: T | None = None
    error: str | None = None
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        provider = self.provider.strip()
        if not provider:
            raise ValueError("provider is required")
        object.__setattr__(self, "provider", provider)
        if self.data is not None and self.error is not None:
            raise ValueError("provider result must include either data or error, not both")
        if self.data is None and self.error is None:
            raise ValueError("provider result must include either data or error")
        if self.error is not None and not self.error.strip():
            raise ValueError("error must not be blank")
        object.__setattr__(self, "warnings", tuple(self.warnings))

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def success(cls, *, provider: str, data: T, warnings: tuple[str, ...] = ()) -> Self:
        return cls(provider=provider, data=data, warnings=warnings)

    @classmethod
    def failure(cls, *, provider: str, error: str, warnings: tuple[str, ...] = ()) -> Self:
        return cls(provider=provider, error=error, warnings=warnings)
