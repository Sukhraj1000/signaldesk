"""Deterministic domain models for market data and provider responses."""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import ClassVar, Self


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
    data_role: str = "price"
    provider_tier: str = "default"
    supports_realtime: bool
    supports_historical: bool
    supported_asset_classes: frozenset[str] = field(default_factory=frozenset)
    supported_intervals: frozenset[str] = field(default_factory=frozenset)
    credential_state: str = "not_required"
    live_check_suitable: bool = False
    max_history_days: int | None = None
    rate_limit_per_minute: int | None = None

    def __post_init__(self) -> None:
        provider = self.provider.strip()
        if not provider:
            raise ValueError("provider is required")
        object.__setattr__(self, "provider", provider)
        data_role = self.data_role.strip().lower().replace(" ", "_")
        if data_role not in {"price", "catalyst", "fundamentals"}:
            raise ValueError("data_role must be price, catalyst, or fundamentals")
        object.__setattr__(self, "data_role", data_role)
        provider_tier = self.provider_tier.strip().lower().replace(" ", "_")
        if provider_tier not in {"default", "enhanced"}:
            raise ValueError("provider_tier must be default or enhanced")
        object.__setattr__(self, "provider_tier", provider_tier)
        normalized_asset_classes = frozenset(
            asset_class.strip().lower()
            for asset_class in self.supported_asset_classes
            if asset_class.strip()
        )
        object.__setattr__(self, "supported_asset_classes", normalized_asset_classes)
        normalized_intervals = frozenset(
            interval.strip().lower()
            for interval in self.supported_intervals
            if interval.strip()
        )
        object.__setattr__(self, "supported_intervals", normalized_intervals)
        credential_state = self.credential_state.strip().lower().replace(" ", "_")
        if credential_state not in {
            "not_required",
            "optional",
            "required",
            "configured",
            "not_configured",
            "placeholder",
        }:
            raise ValueError(
                "credential_state must be not_required, optional, required, "
                "configured, not_configured, or placeholder"
            )
        object.__setattr__(self, "credential_state", credential_state)
        if self.max_history_days is not None and self.max_history_days <= 0:
            raise ValueError("max_history_days must be positive")
        if self.rate_limit_per_minute is not None and self.rate_limit_per_minute <= 0:
            raise ValueError("rate_limit_per_minute must be positive")


def _normalize_error_taxonomy_value(value: str, field_name: str) -> str:
    normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


@dataclass(frozen=True, kw_only=True)
class ProviderError:
    """Actionable, credential-safe provider error taxonomy metadata."""

    code: str
    message: str
    category: str = "provider"
    retryable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "code", _normalize_error_taxonomy_value(self.code, "error code")
        )
        object.__setattr__(
            self,
            "category",
            _normalize_error_taxonomy_value(self.category, "error category"),
        )
        message = self.message.strip()
        if not message:
            raise ValueError("error message is required")
        object.__setattr__(self, "message", message)


@dataclass(frozen=True, kw_only=True)
class ProviderResult[T]:
    """A deterministic wrapper for provider success, warnings, or failure."""

    provider: str
    data: T | None = None
    error: str | None = None
    warnings: tuple[str, ...] = ()
    error_code: str | None = None
    error_category: str | None = None
    retryable: bool = False

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
        if self.error is None:
            if self.error_code is not None or self.error_category is not None or self.retryable:
                raise ValueError("successful provider result must not include error metadata")
        else:
            if self.error_code is not None:
                object.__setattr__(
                    self,
                    "error_code",
                    _normalize_error_taxonomy_value(self.error_code, "error_code"),
                )
            if self.error_category is not None:
                object.__setattr__(
                    self,
                    "error_category",
                    _normalize_error_taxonomy_value(self.error_category, "error_category"),
                )
        object.__setattr__(self, "warnings", tuple(self.warnings))

    @property
    def ok(self) -> bool:
        return self.error is None

    @property
    def provider_error(self) -> ProviderError | None:
        if self.error is None:
            return None
        return ProviderError(
            code=self.error_code or "provider_error",
            category=self.error_category or "provider",
            message=self.error,
            retryable=self.retryable,
        )

    @classmethod
    def success(cls, *, provider: str, data: T, warnings: tuple[str, ...] = ()) -> Self:
        return cls(provider=provider, data=data, warnings=warnings)

    @classmethod
    def failure(
        cls,
        *,
        provider: str,
        error: str,
        warnings: tuple[str, ...] = (),
        error_code: str | None = None,
        error_category: str | None = None,
        retryable: bool = False,
    ) -> Self:
        return cls(
            provider=provider,
            error=error,
            warnings=warnings,
            error_code=error_code,
            error_category=error_category,
            retryable=retryable,
        )


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
class FundamentalContext:
    """Structured provider-sourced company facts kept separate from TA signals."""

    symbol: Symbol
    provider: str
    generated_at: datetime
    company_name: str | None = None
    exchange: str | None = None
    industry: str | None = None
    sector: str | None = None
    market_cap: int | None = None
    currency: str | None = None
    price: Decimal | None = None
    beta: Decimal | None = None
    pe_ratio: Decimal | None = None
    eps: Decimal | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, Symbol):
            raise TypeError("symbol must be a Symbol")
        _require_timezone_aware(self.generated_at)
        provider = self.provider.strip().lower()
        if not provider:
            raise ValueError("provider is required")
        object.__setattr__(self, "provider", provider)
        for field_name in (
            "company_name",
            "exchange",
            "industry",
            "sector",
            "currency",
            "source_url",
        ):
            value = getattr(self, field_name)
            normalized = value.strip() if isinstance(value, str) else None
            object.__setattr__(self, field_name, normalized or None)
        if self.market_cap is not None and self.market_cap < 0:
            raise ValueError("market_cap must be non-negative")
        for field_name in ("price", "beta", "pe_ratio", "eps"):
            value = getattr(self, field_name)
            if value is not None:
                if not isinstance(value, Decimal):
                    raise TypeError(f"{field_name} must be a Decimal")
                if not value.is_finite():
                    raise ValueError(f"{field_name} must be finite")
        if self.price is not None and self.price <= Decimal("0"):
            raise ValueError("price must be positive")


@dataclass(frozen=True, kw_only=True)
class CatalystEvent:
    """Structured provider-sourced catalyst fact kept separate from TA signals."""

    headline: str
    provider: str
    published_at: datetime | None = None
    source: str | None = None
    url: str | None = None
    summary: str | None = None

    def __post_init__(self) -> None:
        headline = self.headline.strip()
        provider = self.provider.strip().lower()
        if not headline:
            raise ValueError("headline is required")
        if not provider:
            raise ValueError("provider is required")
        if self.published_at is not None:
            _require_timezone_aware(self.published_at)
        object.__setattr__(self, "headline", headline)
        object.__setattr__(self, "provider", provider)
        for field_name in ("source", "url", "summary"):
            value = getattr(self, field_name)
            normalized = value.strip() if isinstance(value, str) else None
            object.__setattr__(self, field_name, normalized or None)


@dataclass(frozen=True, kw_only=True)
class CatalystContext:
    """Structured provider-sourced catalyst context kept separate from TA signals."""

    symbol: Symbol
    provider: str
    generated_at: datetime
    events: tuple[CatalystEvent, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, Symbol):
            raise TypeError("symbol must be a Symbol")
        _require_timezone_aware(self.generated_at)
        provider = self.provider.strip().lower()
        if not provider:
            raise ValueError("provider is required")
        events = tuple(self.events)
        if any(not isinstance(event, CatalystEvent) for event in events):
            raise TypeError("catalyst events must be CatalystEvent")
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "events", events)


@dataclass(frozen=True, kw_only=True)
class UnavailableContext:
    """Market context that was unavailable and must not be treated as a false negative."""

    context_type: str
    reason: str
    provider: str | None = None
    details: str | None = None

    def __post_init__(self) -> None:
        context_type = self.context_type.strip().lower().replace(" ", "_")
        reason = self.reason.strip()
        provider = self.provider.strip() if self.provider is not None else None
        details = self.details.strip() if self.details is not None else None
        if not context_type:
            raise ValueError("context_type is required")
        if not reason:
            raise ValueError("reason is required")
        if provider == "":
            provider = None
        if details == "":
            details = None
        object.__setattr__(self, "context_type", context_type)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "details", details)


@dataclass(frozen=True, kw_only=True)
class ProviderMode:
    """Provider tier and selected data/LLM sources for an assembled artifact."""

    mode: str = "default"
    price_provider: str = "yfinance"
    catalyst_provider: str | None = None
    fundamentals_provider: str | None = None
    llm_provider: str | None = None

    def __post_init__(self) -> None:
        mode = self.mode.strip().lower()
        if mode not in {"default", "enhanced"}:
            raise ValueError("mode must be default or enhanced")
        price_provider = self.price_provider.strip().lower()
        if not price_provider:
            raise ValueError("price_provider is required")
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "price_provider", price_provider)
        for field_name in (
            "catalyst_provider",
            "fundamentals_provider",
            "llm_provider",
        ):
            provider = getattr(self, field_name)
            normalized_provider = provider.strip().lower() if provider is not None else None
            object.__setattr__(self, field_name, normalized_provider or None)


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
        normalized_indicators: dict[str, Decimal] = {}
        original_indicator_names: dict[str, list[str]] = {}
        for name, value in self.indicators.items():
            normalized_name = name.strip().lower()
            if not normalized_name:
                continue
            original_indicator_names.setdefault(normalized_name, []).append(name)
            normalized_indicators[normalized_name] = value
        collided_indicators = {
            normalized_name: names
            for normalized_name, names in original_indicator_names.items()
            if len(names) > 1
        }
        if collided_indicators:
            collision_details = ", ".join(
                f"{normalized_name}: {names}"
                for normalized_name, names in sorted(collided_indicators.items())
            )
            raise ValueError(f"indicator names collide after normalization: {collision_details}")
        for name, value in normalized_indicators.items():
            if not isinstance(value, Decimal):
                raise TypeError(f"indicator {name} must be a Decimal")
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "trend", trend)
        object.__setattr__(self, "events", tuple(self.events))
        object.__setattr__(self, "indicators", normalized_indicators)


@dataclass(frozen=True, kw_only=True)
class RiskFlag:
    """A typed deterministic risk attached to an analysis artifact."""

    kind: str
    severity: str
    message: str
    source: str | None = None

    ALLOWED_SEVERITIES: ClassVar[tuple[str, ...]] = ("info", "warning", "critical")

    def __post_init__(self) -> None:
        kind = self.kind.strip().lower().replace(" ", "_")
        severity = self.severity.strip().lower()
        message = self.message.strip()
        source = (
            self.source.strip().lower().replace(" ", "_")
            if self.source is not None
            else None
        )
        if not kind:
            raise ValueError("kind is required")
        if severity not in self.ALLOWED_SEVERITIES:
            raise ValueError("severity must be info, warning, or critical")
        if not message:
            raise ValueError("message is required")
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "severity", severity)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "source", source or None)


@dataclass(frozen=True, kw_only=True)
class RiskAssessment:
    """A canonical risk container with typed flags and an overall severity."""

    flags: tuple[RiskFlag, ...]
    overall_severity: str | None = None

    _SEVERITY_RANK: ClassVar[dict[str, int]] = {"info": 0, "warning": 1, "critical": 2}

    def __post_init__(self) -> None:
        flags = tuple(self.flags)
        if not flags:
            raise ValueError("risk assessment must include at least one flag")
        if any(not isinstance(flag, RiskFlag) for flag in flags):
            raise TypeError("risk assessment flags must be RiskFlag")
        highest_flag = max(
            flags,
            key=lambda flag: self._SEVERITY_RANK[flag.severity],
        )
        if self.overall_severity is None:
            overall_severity = highest_flag.severity
        else:
            overall_severity = self.overall_severity.strip().lower()
            if overall_severity not in self._SEVERITY_RANK:
                raise ValueError("overall_severity must be info, warning, or critical")
            if (
                self._SEVERITY_RANK[overall_severity]
                < self._SEVERITY_RANK[highest_flag.severity]
            ):
                raise ValueError(
                    "overall_severity must not be lower than highest flag severity"
                )
        object.__setattr__(self, "flags", flags)
        object.__setattr__(self, "overall_severity", overall_severity)


@dataclass(frozen=True, kw_only=True)
class ScoreReason:
    """A traceable deterministic reason contributing to a score."""

    code: str
    message: str
    source: str
    weight: Decimal | None = None

    def __post_init__(self) -> None:
        code = self.code.strip().lower().replace(" ", "_")
        message = self.message.strip()
        source = self.source.strip().lower().replace(" ", "_")
        if not code:
            raise ValueError("code is required")
        if not message:
            raise ValueError("message is required")
        if not source:
            raise ValueError("source is required")
        if self.weight is not None:
            if not isinstance(self.weight, Decimal):
                raise TypeError("weight must be a Decimal")
            if self.weight < Decimal("0") or self.weight > Decimal("1"):
                raise ValueError("weight must be between 0 and 1")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "source", source)


@dataclass(frozen=True, kw_only=True)
class ScoreBreakdown:
    """A bounded score with deterministic reasons for one score category."""

    category: str
    score: Decimal
    reasons: tuple[ScoreReason, ...]

    ALLOWED_CATEGORIES: ClassVar[tuple[str, ...]] = (
        "setup_quality",
        "risk",
        "data_quality",
    )

    def __post_init__(self) -> None:
        category = self.category.strip().lower().replace(" ", "_")
        if category not in self.ALLOWED_CATEGORIES:
            raise ValueError("category must be setup_quality, risk, or data_quality")
        if not isinstance(self.score, Decimal):
            raise TypeError("score must be a Decimal")
        if self.score < Decimal("0") or self.score > Decimal("100"):
            raise ValueError("score must be between 0 and 100")
        reasons = tuple(self.reasons)
        if not reasons:
            raise ValueError("score breakdown must include at least one reason")
        if any(not isinstance(reason, ScoreReason) for reason in reasons):
            raise TypeError("score breakdown reasons must be ScoreReason")
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "reasons", reasons)


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
    provider_mode: ProviderMode | None = None
    provenance: tuple[Provenance, ...] = ()
    unavailable_context: tuple[UnavailableContext, ...] = ()
    risk_assessment: RiskAssessment | None = None
    scores: tuple[ScoreBreakdown, ...] = ()
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
        if not isinstance(self.confidence, Decimal):
            raise TypeError("confidence must be a Decimal")
        if self.confidence < Decimal("0") or self.confidence > Decimal("1"):
            raise ValueError("confidence must be between 0 and 1")
        object.__setattr__(self, "timeframe", timeframe)
        object.__setattr__(self, "bias", bias)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "events", tuple(self.events))
        if self.provider_mode is not None and not isinstance(self.provider_mode, ProviderMode):
            raise TypeError("provider_mode must be ProviderMode")
        object.__setattr__(self, "provenance", tuple(self.provenance))
        unavailable_context = tuple(self.unavailable_context)
        if any(not isinstance(entry, UnavailableContext) for entry in unavailable_context):
            raise TypeError("unavailable_context entries must be UnavailableContext")
        object.__setattr__(self, "unavailable_context", unavailable_context)
        if self.risk_assessment is not None and not isinstance(
            self.risk_assessment, RiskAssessment
        ):
            raise TypeError("risk_assessment must be RiskAssessment")
        scores = tuple(self.scores)
        if any(not isinstance(score, ScoreBreakdown) for score in scores):
            raise TypeError("scores entries must be ScoreBreakdown")
        object.__setattr__(self, "scores", scores)
        normalized_tags = tuple(tag.strip().lower() for tag in self.tags if tag.strip())
        object.__setattr__(self, "tags", normalized_tags)
