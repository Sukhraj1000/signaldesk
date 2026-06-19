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


@dataclass(frozen=True, kw_only=True)
class Provenance:
    """Provider-agnostic inputs used to generate an analysis artifact."""

    provider: str
    source: str
    generated_at: datetime
    timeframe: str
    inputs: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_timezone_aware(self.generated_at)
        provider = self.provider.strip()
        source = self.source.strip()
        timeframe = self.timeframe.strip()
        if not provider:
            raise ValueError("provider is required")
        if not source:
            raise ValueError("source is required")
        if not timeframe:
            raise ValueError("timeframe is required")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "timeframe", timeframe)
        normalized_inputs = tuple(item.strip() for item in self.inputs if item.strip())
        object.__setattr__(self, "inputs", normalized_inputs)
        object.__setattr__(self, "warnings", tuple(self.warnings))


@dataclass(frozen=True, kw_only=True)
class KeyLevels:
    """Support, resistance, and trade-planning levels derived from analysis."""

    support: tuple[Decimal, ...] = ()
    resistance: tuple[Decimal, ...] = ()
    confirmation: Decimal | None = None
    invalidation: Decimal | None = None

    def __post_init__(self) -> None:
        support = tuple(self.support)
        resistance = tuple(self.resistance)
        has_no_levels = (
            not support
            and not resistance
            and self.confirmation is None
            and self.invalidation is None
        )
        if has_no_levels:
            raise ValueError("key levels must include at least one level")
        for field_name, levels in (("support", support), ("resistance", resistance)):
            for level in levels:
                _require_positive_decimal(level, field_name)
        for field_name in ("confirmation", "invalidation"):
            value = getattr(self, field_name)
            if value is not None:
                _require_positive_decimal(value, field_name)
        object.__setattr__(self, "support", support)
        object.__setattr__(self, "resistance", resistance)


@dataclass(frozen=True, kw_only=True)
class TechnicalEvent:
    """A deterministic technical-analysis event observed at a point in time."""

    event_type: str
    observed_at: datetime
    summary: str
    price: Decimal | None = None
    severity: str = "info"

    def __post_init__(self) -> None:
        _require_timezone_aware(self.observed_at)
        event_type = self.event_type.strip().lower().replace(" ", "_")
        summary = self.summary.strip()
        severity = self.severity.strip().lower()
        if not event_type:
            raise ValueError("event_type is required")
        if not summary:
            raise ValueError("summary is required")
        if severity not in {"info", "bullish", "bearish", "warning"}:
            raise ValueError("severity must be info, bullish, bearish, or warning")
        if self.price is not None:
            _require_positive_decimal(self.price, "price")
        object.__setattr__(self, "event_type", event_type)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "severity", severity)


@dataclass(frozen=True, kw_only=True)
class TechnicalSnapshot:
    """A typed technical-analysis snapshot for a symbol and timeframe."""

    symbol: Symbol
    as_of: datetime
    timeframe: str
    trend: str
    last_price: Decimal
    key_levels: KeyLevels
    events: tuple[TechnicalEvent, ...] = ()
    provenance: Provenance | None = None
    indicators: dict[str, Decimal] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_timezone_aware(self.as_of)
        timeframe = self.timeframe.strip()
        trend = self.trend.strip().lower()
        if not timeframe:
            raise ValueError("timeframe is required")
        if trend not in {"up", "down", "sideways", "unknown"}:
            raise ValueError("trend must be up, down, sideways, or unknown")
        _require_positive_decimal(self.last_price, "last_price")
        normalized_indicators = {
            name.strip().lower(): value
            for name, value in self.indicators.items()
            if name.strip()
        }
        for name, value in normalized_indicators.items():
            if not isinstance(value, Decimal):
                raise TypeError(f"indicator {name} must be a Decimal")
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "trend", trend)
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "indicators", normalized_indicators)


@dataclass(frozen=True, kw_only=True)
class SignalCard:
    """A compact provider-agnostic signal summary assembled from analysis facts."""

    symbol: Symbol
    generated_at: datetime
    timeframe: str
    bias: str
    summary: str
    confidence: Decimal
    snapshot: TechnicalSnapshot | None = None
    key_levels: KeyLevels | None = None
    events: tuple[TechnicalEvent, ...] = ()
    provenance: tuple[Provenance, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_timezone_aware(self.generated_at)
        timeframe = self.timeframe.strip()
        bias = self.bias.strip().lower()
        summary = self.summary.strip()
        if not timeframe:
            raise ValueError("timeframe is required")
        if bias not in {"bullish", "bearish", "neutral", "watch"}:
            raise ValueError("bias must be bullish, bearish, neutral, or watch")
        if not summary:
            raise ValueError("summary is required")
        if self.confidence < Decimal("0") or self.confidence > Decimal("1"):
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "bias", bias)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "provenance", tuple(self.provenance))
        normalized_tags = tuple(tag.strip().lower() for tag in self.tags if tag.strip())
        object.__setattr__(self, "tags", normalized_tags)
