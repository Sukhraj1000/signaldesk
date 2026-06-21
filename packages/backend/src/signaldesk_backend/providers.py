"""Provider contracts, adapters, and registry for market-data providers."""

import csv
import io
import json
import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from functools import partial
from importlib import import_module
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

from signaldesk_backend.models import (
    Candle,
    ProviderCapability,
    ProviderResult,
    Quote,
    Symbol,
)

_CREDENTIAL_QUERY_KEYS = frozenset(
    {"apikey", "api_key", "token", "access_token", "secret", "password"}
)
_URL_PATTERN = re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s]+")
_CREDENTIAL_SUBSTRING_PATTERN = re.compile(
    r"\b(apikey|api_key|x-api-key|access_token|token|secret|password)\b(\s*[:=]\s*|\s+)([^\s&;,]+)",
    re.IGNORECASE,
)


def redact_provider_diagnostic(text: object) -> str:
    """Redact credential-like values from provider diagnostic text.

    The helper preserves useful non-secret context such as URL host/path and
    non-sensitive query parameters while replacing obvious credential values.
    """

    diagnostic = str(text)
    diagnostic = _URL_PATTERN.sub(_redact_url_match, diagnostic)
    return _CREDENTIAL_SUBSTRING_PATTERN.sub(_redact_credential_substring, diagnostic)


def _redact_url_match(match: re.Match[str]) -> str:
    url = match.group(0)
    trailing = ""
    while url and url[-1] in ".,);]}":
        trailing = url[-1] + trailing
        url = url[:-1]

    parts = urlsplit(url)
    safe_netloc = parts.netloc
    if "@" in safe_netloc:
        host = safe_netloc.rsplit("@", 1)[1]
        safe_netloc = f"<redacted>@{host}"
    if not parts.query:
        if safe_netloc == parts.netloc:
            return match.group(0)
        return (
            f"{urlunsplit((parts.scheme, safe_netloc, parts.path, '', parts.fragment))}"
            f"{trailing}"
        )

    query = [
        (key, "<redacted>" if key.lower() in _CREDENTIAL_QUERY_KEYS else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    redacted_url = urlunsplit(
        (
            parts.scheme,
            safe_netloc,
            parts.path,
            urlencode(query, safe="<>", doseq=True),
            parts.fragment,
        )
    )
    return f"{redacted_url}{trailing}"


def _redact_credential_substring(match: re.Match[str]) -> str:
    return f"{match.group(1)}{match.group(2)}<redacted>"


def provider_rate_limit_failure(
    provider: str, diagnostic: object | None = None
) -> ProviderResult[Any]:
    """Return a stable, credential-safe failure for provider rate limits.

    Adapters can pass provider-specific HTTP errors or throttling diagnostics to
    preserve useful context. Credential-like values are redacted before the text
    is exposed through ``ProviderResult.error``.
    """

    error = f"{provider} request was rate limited"
    if diagnostic is not None:
        safe_diagnostic = redact_provider_diagnostic(diagnostic).strip()
        if safe_diagnostic:
            error = f"{error}: {safe_diagnostic}"
    return ProviderResult.failure(provider=provider, error=error)


def _http_error_rate_limit_diagnostic(exc: HTTPError) -> str:
    return f"{exc} {exc.url}"


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


def fallback_provider_call[T](
    provider_calls: Iterable[Callable[[], ProviderResult[T]]],
    *,
    failure_provider: str = "provider-fallback",
) -> ProviderResult[T]:
    """Return the first successful provider result from ordered provider calls.

    Each callable should perform one provider lookup and return a ``ProviderResult``.
    Provider failures are treated as expected fallback signals; their provider/error
    pairs are preserved in the final failure result when every provider fails.
    Successful results are returned unchanged so downstream provenance still points
    at the provider that actually supplied the data.
    """

    failures: list[str] = []
    for provider_call in provider_calls:
        try:
            result = provider_call()
        except Exception as exc:
            failures.append(_provider_exception_summary(provider_call, exc))
            continue
        if result.ok:
            return result
        failures.append(_provider_failure_summary(result))

    if not failures:
        return ProviderResult.failure(
            provider=failure_provider,
            error="no providers configured for fallback",
        )
    return ProviderResult.failure(
        provider=failure_provider,
        error=f"all providers failed: {'; '.join(failures)}",
        warnings=tuple(failures),
    )


def _provider_failure_summary(result: ProviderResult[Any]) -> str:
    error = redact_provider_diagnostic(
        result.error or "provider returned an unknown failure"
    )
    return f"{result.provider}: {error}"


def _provider_exception_summary(
    provider_call: Callable[[], ProviderResult[Any]], exc: Exception
) -> str:
    provider = _provider_call_name(provider_call)
    error = redact_provider_diagnostic(f"{type(exc).__name__}: {exc}")
    return f"{provider}: {error}"


def _provider_call_name(provider_call: Callable[[], ProviderResult[Any]]) -> str:
    bound_self = getattr(provider_call, "__self__", None)
    if bound_self is not None:
        name = getattr(bound_self, "name", None)
        if isinstance(name, str) and name.strip():
            return name

    partial_func = getattr(provider_call, "func", None)
    partial_self = getattr(partial_func, "__self__", None)
    if partial_self is not None:
        name = getattr(partial_self, "name", None)
        if isinstance(name, str) and name.strip():
            return name

    partial_args = getattr(provider_call, "args", ())
    if partial_args:
        name = getattr(partial_args[0], "name", None)
        if isinstance(name, str) and name.strip():
            return name

    return "unknown-provider"


@dataclass(frozen=True)
class FallbackProvider:
    """Market-data provider wrapper that tries providers in the supplied order."""

    providers: tuple[MarketDataProvider, ...]
    name: str = "provider-fallback"

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        """Return the concatenated capabilities advertised by fallback members."""

        capabilities: list[ProviderCapability] = []
        for provider in self.providers:
            capabilities.extend(provider.capabilities())
        return tuple(capabilities)

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        """Fetch candles from the first fallback member that succeeds."""

        return fallback_provider_call(
            (
                partial(
                    provider.get_historical_candles,
                    symbol,
                    start=start,
                    end=end,
                    interval=interval,
                )
                for provider in self.providers
            ),
            failure_provider=self.name,
        )

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        """Fetch a quote from the first fallback member that succeeds."""

        return fallback_provider_call(
            (partial(provider.get_quote, symbol) for provider in self.providers),
            failure_provider=self.name,
        )

    def health_check(self) -> ProviderResult[str]:
        """Return the first successful member health check, or all failures."""

        return fallback_provider_call(
            (provider.health_check for provider in self.providers),
            failure_provider=self.name,
        )


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
    """Built-in deterministic provider for local health checks and smoke tests."""

    name: str = "local-fixture"

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        """Return safe local-only capabilities for CLI discovery."""

        return (
            ProviderCapability(
                provider=self.name,
                supports_realtime=False,
                supports_historical=True,
                supported_asset_classes=frozenset({"equity", "fixture"}),
                supported_intervals=frozenset({"1d"}),
                credential_state="not_required",
                live_check_suitable=True,
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
        """Return deterministic daily candles without network or credentials."""

        if start > end:
            return ProviderResult.failure(provider=self.name, error="start must be before end")
        if interval.strip().lower() != "1d":
            return ProviderResult.failure(
                provider=self.name,
                error="local fixture supports only daily historical intervals",
            )

        start_timestamp = datetime.combine(start.date(), time.min, tzinfo=UTC)
        end_timestamp = datetime.combine(end.date(), time.min, tzinfo=UTC)
        candles: list[Candle] = []
        for index in range(60):
            candle_timestamp = end_timestamp - timedelta(days=59 - index)
            if start_timestamp <= candle_timestamp <= end_timestamp:
                candles.append(
                    Candle(
                        symbol=symbol,
                        timestamp=candle_timestamp,
                        open=Decimal(index + 100),
                        high=Decimal(index + 102),
                        low=Decimal(index + 98),
                        close=Decimal(index + 101),
                        volume=10_000 + index,
                    )
                )
        fixture_candles = tuple(candles)
        if not fixture_candles:
            return ProviderResult.failure(
                provider=self.name,
                error="local fixture returned no candles for requested date range",
            )

        return ProviderResult.success(provider=self.name, data=fixture_candles)

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
            data="ready (deterministic historical candles; no external credentials required)",
        )


@dataclass(frozen=True)
class LocalCsvProvider:
    """Local deterministic CSV-backed historical candle provider.

    Required CSV columns are: ``Date``, ``Open``, ``High``, ``Low``, ``Close``, and
    ``Volume``. Dates use ``YYYY-MM-DD`` and filtering is inclusive against the UTC
    candle timestamp derived from each date.
    """

    csv_path: str | Path
    name: str = "local-csv"

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        """Return local historical candle capabilities without reading the file."""

        return (
            ProviderCapability(
                provider=self.name,
                supports_realtime=False,
                supports_historical=True,
                supported_asset_classes=frozenset({"equity", "etf", "crypto", "index"}),
                supported_intervals=frozenset({"1d"}),
                credential_state="not_required",
                live_check_suitable=True,
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
        """Load historical daily candles from a local CSV file and filter by date."""

        if start > end:
            return ProviderResult.failure(provider=self.name, error="start must be before end")
        if not self._supports_interval(interval):
            return ProviderResult.failure(
                provider=self.name,
                error="local csv supports only daily historical intervals",
            )

        path = Path(self.csv_path).expanduser()
        try:
            with path.open(newline="", encoding="utf-8-sig") as csv_file:
                reader = csv.DictReader(csv_file)
                return self._parse_rows(symbol, reader, start=start, end=end)
        except FileNotFoundError:
            return ProviderResult.failure(provider=self.name, error="local csv file was not found")
        except (OSError, UnicodeDecodeError, csv.Error):
            return ProviderResult.failure(
                provider=self.name, error="local csv historical data was invalid"
            )

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        """Report that this adapter currently supports historical candles only."""

        return ProviderResult.failure(
            provider=self.name, error="local csv quote retrieval is not supported"
        )

    def health_check(self) -> ProviderResult[str]:
        """Return a deterministic local file status without exposing path details."""

        if not Path(self.csv_path).expanduser().is_file():
            return ProviderResult.failure(provider=self.name, error="local csv file was not found")
        return ProviderResult.success(
            provider=self.name,
            data="ready (local CSV file available; no external credentials required)",
        )

    def _parse_rows(
        self,
        symbol: Symbol,
        reader: csv.DictReader[str],
        *,
        start: datetime,
        end: datetime,
    ) -> ProviderResult[tuple[Candle, ...]]:
        required_columns = {"Date", "Open", "High", "Low", "Close", "Volume"}
        if not reader.fieldnames or not required_columns.issubset(set(reader.fieldnames)):
            return ProviderResult.failure(
                provider=self.name, error="local csv missing required columns"
            )

        candles: list[Candle] = []
        try:
            for row in reader:
                if not any(value and value.strip() for value in row.values()):
                    continue
                candle = self._row_to_candle(symbol, row)
                if start <= candle.timestamp <= end:
                    candles.append(candle)
        except (TypeError, ValueError, InvalidOperation):
            return ProviderResult.failure(
                provider=self.name, error="local csv historical data was invalid"
            )

        if not candles:
            return ProviderResult.failure(
                provider=self.name, error=f"no historical data for {symbol.ticker} in local csv"
            )
        return ProviderResult.success(provider=self.name, data=tuple(candles))

    def _row_to_candle(self, symbol: Symbol, row: dict[str, str]) -> Candle:
        return Candle(
            symbol=symbol,
            timestamp=self._date_from_text(row.get("Date")),
            open=self._decimal_from_text(row.get("Open")),
            high=self._decimal_from_text(row.get("High")),
            low=self._decimal_from_text(row.get("Low")),
            close=self._decimal_from_text(row.get("Close")),
            volume=self._volume_from_text(row.get("Volume")),
        )

    def _date_from_text(self, value: str | None) -> datetime:
        if value is None or not value.strip():
            raise ValueError("date is required")
        return datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=UTC)

    def _decimal_from_text(self, value: str | None) -> Decimal:
        if value is None or not value.strip():
            raise ValueError("price is required")
        decimal_value = Decimal(value.strip())
        if not decimal_value.is_finite() or decimal_value <= Decimal("0"):
            raise ValueError("price must be positive")
        return decimal_value

    def _volume_from_text(self, value: str | None) -> int:
        if value is None or not value.strip():
            raise ValueError("volume is required")
        volume = Decimal(value.strip())
        if not volume.is_finite() or volume < Decimal("0") or volume != volume.to_integral_value():
            raise ValueError("volume must be a non-negative integer")
        return int(volume)

    def _supports_interval(self, interval: str) -> bool:
        return interval.strip().lower() in {"d", "1d", "day", "daily"}


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
                supported_intervals=frozenset(
                    {
                        "1m",
                        "2m",
                        "5m",
                        "15m",
                        "30m",
                        "60m",
                        "90m",
                        "1h",
                        "1d",
                        "5d",
                        "1wk",
                        "1mo",
                        "3mo",
                    }
                ),
                credential_state="not_required",
                live_check_suitable=False,
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


@dataclass(frozen=True)
class StooqProvider:
    """No-key Stooq CSV-backed historical candle provider adapter."""

    name: str = "stooq"
    base_url: str = "https://stooq.com/q/d/l/"
    timeout_seconds: float = 10.0
    _urlopen: Any | None = field(default=None, repr=False, compare=False)

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        """Return Stooq historical candle capabilities without performing network I/O."""

        return (
            ProviderCapability(
                provider=self.name,
                supports_realtime=False,
                supports_historical=True,
                supported_asset_classes=frozenset({"equity", "etf", "index"}),
                supported_intervals=frozenset({"1d", "1wk", "1mo"}),
                credential_state="not_required",
                live_check_suitable=False,
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
        """Fetch daily/weekly/monthly candles from Stooq CSV and normalize them."""

        if start > end:
            return ProviderResult.failure(provider=self.name, error="start must be before end")

        stooq_interval = self._normalize_interval(interval)
        if stooq_interval is None:
            return ProviderResult.failure(
                provider=self.name,
                error="stooq supports only daily, weekly, and monthly historical intervals",
            )

        request = Request(self._historical_url(symbol, start, end, stooq_interval))
        opener = self._urlopen or urlopen
        try:
            with opener(request, timeout=self.timeout_seconds) as response:
                body = response.read()
        except HTTPError as exc:
            if exc.code == 429:
                return provider_rate_limit_failure(
                    self.name, _http_error_rate_limit_diagnostic(exc)
                )
            return ProviderResult.failure(provider=self.name, error="stooq historical fetch failed")
        except (OSError, URLError, TimeoutError):
            return ProviderResult.failure(provider=self.name, error="stooq historical fetch failed")

        try:
            text = body.decode("utf-8-sig") if isinstance(body, bytes) else str(body)
        except UnicodeDecodeError:
            return ProviderResult.failure(
                provider=self.name, error="stooq historical data was invalid"
            )

        return self._parse_csv(symbol, text)

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        """Report that this adapter currently supports historical candles only."""

        return ProviderResult.failure(
            provider=self.name, error="stooq quote retrieval is not supported"
        )

    def health_check(self) -> ProviderResult[str]:
        """Return a deterministic no-secret status without calling Stooq."""

        return ProviderResult.success(
            provider=self.name,
            data="ready (no external credentials required; network used only for candle fetches)",
        )

    def _historical_url(
        self, symbol: Symbol, start: datetime, end: datetime, stooq_interval: str
    ) -> str:
        query = urlencode(
            {
                "s": self._stooq_symbol(symbol),
                "d1": start.strftime("%Y%m%d"),
                "d2": end.strftime("%Y%m%d"),
                "i": stooq_interval,
            }
        )
        return f"{self.base_url}?{query}"

    def _stooq_symbol(self, symbol: Symbol) -> str:
        ticker = symbol.ticker.lower().replace("/", "-")
        if "." in ticker:
            return ticker
        if symbol.exchange is None or symbol.exchange in {"US", "NASDAQ", "NYSE", "AMEX"}:
            return f"{ticker}.us"
        return f"{ticker}.{symbol.exchange.lower()}"

    def _normalize_interval(self, interval: str) -> str | None:
        normalized = interval.strip().lower()
        interval_map = {
            "d": "d",
            "1d": "d",
            "day": "d",
            "daily": "d",
            "w": "w",
            "1wk": "w",
            "1w": "w",
            "week": "w",
            "weekly": "w",
            "m": "m",
            "1mo": "m",
            "1m": "m",
            "month": "m",
            "monthly": "m",
        }
        return interval_map.get(normalized)

    def _parse_csv(self, symbol: Symbol, text: str) -> ProviderResult[tuple[Candle, ...]]:
        if not text.strip() or text.strip().lower() == "no data":
            return ProviderResult.failure(
                provider=self.name, error=f"no historical data for {symbol.ticker}"
            )

        reader = csv.DictReader(io.StringIO(text))
        required_columns = {"Date", "Open", "High", "Low", "Close", "Volume"}
        if not reader.fieldnames or not required_columns.issubset(set(reader.fieldnames)):
            return ProviderResult.failure(
                provider=self.name, error="stooq historical data was invalid"
            )

        candles: list[Candle] = []
        try:
            for row in reader:
                candle = self._row_to_candle(symbol, row)
                if candle is not None:
                    candles.append(candle)
        except (TypeError, ValueError, InvalidOperation):
            return ProviderResult.failure(
                provider=self.name, error="stooq historical data was invalid"
            )

        if not candles:
            return ProviderResult.failure(
                provider=self.name, error=f"no usable historical data for {symbol.ticker}"
            )
        return ProviderResult.success(provider=self.name, data=tuple(candles))

    def _row_to_candle(self, symbol: Symbol, row: dict[str, str]) -> Candle | None:
        if not any(value.strip() for value in row.values() if value is not None):
            return None
        open_price = self._decimal_from_text(row.get("Open"))
        high = self._decimal_from_text(row.get("High"))
        low = self._decimal_from_text(row.get("Low"))
        close = self._decimal_from_text(row.get("Close"))
        volume = self._volume_from_text(row.get("Volume"))
        if open_price is None or high is None or low is None or close is None or volume is None:
            return None
        return Candle(
            symbol=symbol,
            timestamp=self._date_from_text(row.get("Date")),
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )

    def _date_from_text(self, value: str | None) -> datetime:
        if value is None:
            raise ValueError("date is required")
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)

    def _decimal_from_text(self, value: str | None) -> Decimal | None:
        if value is None or not value.strip():
            return None
        decimal_value = Decimal(value.strip())
        if not decimal_value.is_finite() or decimal_value <= Decimal("0"):
            return None
        return decimal_value

    def _volume_from_text(self, value: str | None) -> int | None:
        if value is None or not value.strip():
            return 0
        volume = Decimal(value.strip())
        if not volume.is_finite() or volume < Decimal("0"):
            return None
        return int(volume)


@dataclass(frozen=True)
class FmpProvider:
    """Optional Financial Modeling Prep provider adapter.

    The API key is read from ``FMP_API_KEY`` unless injected for tests. Health and
    capability discovery do not perform network I/O or expose credential values.
    """

    name: str = "fmp"
    api_key: str | None = field(default=None, repr=False, compare=False)
    base_url: str = "https://financialmodelingprep.com/api/v3"
    timeout_seconds: float = 10.0
    _urlopen: Any | None = field(default=None, repr=False, compare=False)

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        """Return FMP quote and historical candle capabilities without network I/O."""

        return (
            ProviderCapability(
                provider=self.name,
                supports_realtime=True,
                supports_historical=True,
                supported_asset_classes=frozenset({"equity", "etf", "index"}),
                supported_intervals=frozenset({"1d"}),
                credential_state="required",
                live_check_suitable=False,
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
        """Fetch daily historical candles from FMP and normalize them."""

        api_key = self._api_key()
        if api_key is None:
            return self._missing_key_failure()
        if start > end:
            return ProviderResult.failure(provider=self.name, error="start must be before end")
        if not self._supports_interval(interval):
            return ProviderResult.failure(
                provider=self.name, error="fmp supports only daily historical intervals"
            )

        response = self._fetch_json(
            f"historical-price-full/{symbol.ticker}",
            {
                "from": start.strftime("%Y-%m-%d"),
                "to": end.strftime("%Y-%m-%d"),
                "apikey": api_key,
            },
        )
        if not response.ok:
            return ProviderResult.failure(
                provider=self.name, error=response.error or "fmp request failed"
            )
        return self._parse_candles(symbol, response.data)

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        """Fetch a point-in-time quote from FMP and normalize it."""

        api_key = self._api_key()
        if api_key is None:
            return self._missing_key_failure()
        response = self._fetch_json(f"quote/{symbol.ticker}", {"apikey": api_key})
        if not response.ok:
            return ProviderResult.failure(
                provider=self.name, error=response.error or "fmp request failed"
            )
        return self._parse_quote(symbol, response.data)

    def health_check(self) -> ProviderResult[str]:
        """Report FMP credential readiness without making a live API call."""

        if self._api_key() is None:
            return ProviderResult.success(
                provider=self.name, data="unavailable until FMP credentials are configured"
            )
        return ProviderResult.success(provider=self.name, data="ready (FMP credentials configured)")

    def _api_key(self) -> str | None:
        key = self.api_key if self.api_key is not None else os.getenv("FMP_API_KEY")
        if key is None or not key.strip():
            return None
        return key.strip()

    def _missing_key_failure(self) -> ProviderResult[Any]:
        return ProviderResult.failure(
            provider=self.name, error="FMP credentials are not configured"
        )

    def _fetch_json(self, path: str, query: dict[str, str]) -> ProviderResult[Any]:
        request = Request(self._url(path, query))
        opener = self._urlopen or urlopen
        try:
            with opener(request, timeout=self.timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                if status == 429:
                    return provider_rate_limit_failure(self.name)
                if status >= 400:
                    return ProviderResult.failure(provider=self.name, error="fmp request failed")
                body = response.read()
        except HTTPError as exc:
            if exc.code == 429:
                return provider_rate_limit_failure(
                    self.name, _http_error_rate_limit_diagnostic(exc)
                )
            return ProviderResult.failure(provider=self.name, error="fmp request failed")
        except (OSError, URLError, TimeoutError):
            return ProviderResult.failure(provider=self.name, error="fmp request failed")

        try:
            text = body.decode("utf-8") if isinstance(body, bytes) else str(body)
            return ProviderResult.success(provider=self.name, data=json.loads(text))
        except (TypeError, ValueError, UnicodeDecodeError):
            return ProviderResult.failure(provider=self.name, error="fmp response was invalid")

    def _url(self, path: str, query: dict[str, str]) -> str:
        clean_base = self.base_url.rstrip("/")
        clean_path = path.strip("/")
        return f"{clean_base}/{clean_path}?{urlencode(query)}"

    def _parse_quote(self, symbol: Symbol, payload: Any) -> ProviderResult[Quote]:
        if not isinstance(payload, list) or not payload or not isinstance(payload[0], dict):
            return ProviderResult.failure(provider=self.name, error="fmp quote data was invalid")
        row = payload[0]
        last = self._decimal_from_value(row.get("price"))
        bid = self._decimal_from_value(row.get("bid"))
        ask = self._decimal_from_value(row.get("ask"))
        timestamp = self._timestamp_from_value(row.get("timestamp"))
        if last is None and bid is None and ask is None:
            return ProviderResult.failure(
                provider=self.name, error=f"no quote data for {symbol.ticker}"
            )
        try:
            return ProviderResult.success(
                provider=self.name,
                data=Quote(symbol=symbol, timestamp=timestamp, bid=bid, ask=ask, last=last),
            )
        except ValueError:
            return ProviderResult.failure(provider=self.name, error="fmp quote data was invalid")

    def _parse_candles(self, symbol: Symbol, payload: Any) -> ProviderResult[tuple[Candle, ...]]:
        if not isinstance(payload, dict):
            return ProviderResult.failure(
                provider=self.name, error="fmp historical data was invalid"
            )
        rows = payload.get("historical")
        if not isinstance(rows, list):
            return ProviderResult.failure(
                provider=self.name, error=f"no historical data for {symbol.ticker}"
            )
        candles: list[Candle] = []
        try:
            for row in rows:
                if isinstance(row, dict):
                    candle = self._row_to_candle(symbol, row)
                    if candle is not None:
                        candles.append(candle)
        except (TypeError, ValueError, InvalidOperation):
            return ProviderResult.failure(
                provider=self.name, error="fmp historical data was invalid"
            )
        if not candles:
            return ProviderResult.failure(
                provider=self.name, error=f"no usable historical data for {symbol.ticker}"
            )
        return ProviderResult.success(
            provider=self.name, data=tuple(sorted(candles, key=lambda candle: candle.timestamp))
        )

    def _row_to_candle(self, symbol: Symbol, row: dict[str, Any]) -> Candle | None:
        open_price = self._decimal_from_value(row.get("open"))
        high = self._decimal_from_value(row.get("high"))
        low = self._decimal_from_value(row.get("low"))
        close = self._decimal_from_value(row.get("close"))
        volume = self._volume_from_value(row.get("volume"))
        if open_price is None or high is None or low is None or close is None or volume is None:
            return None
        return Candle(
            symbol=symbol,
            timestamp=self._date_from_text(row.get("date")),
            open=open_price,
            high=high,
            low=low,
            close=close,
            volume=volume,
        )

    def _date_from_text(self, value: object) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("date is required")
        return datetime.strptime(value.strip(), "%Y-%m-%d").replace(tzinfo=UTC)

    def _timestamp_from_value(self, value: object) -> datetime:
        if isinstance(value, int | float):
            return datetime.fromtimestamp(value, tz=UTC)
        return datetime.now(UTC)

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

    def _volume_from_value(self, value: object) -> int | None:
        if value is None or value == "":
            return 0
        try:
            volume = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
        if not volume.is_finite() or volume < Decimal("0"):
            return None
        return int(volume)

    def _supports_interval(self, interval: str) -> bool:
        return interval.strip().lower() in {"d", "1d", "day", "daily"}


@dataclass(frozen=True)
class PlaceholderEnhancedProvider:
    """Offline placeholder for planned credentialed enhanced-data providers."""

    name: str
    display_name: str
    supported_asset_classes: frozenset[str] = frozenset({"equity", "etf", "index"})

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        """Advertise planned provider capabilities without network or secret checks."""

        return (
            ProviderCapability(
                provider=self.name,
                supports_realtime=True,
                supports_historical=True,
                supported_asset_classes=self.supported_asset_classes,
                supported_intervals=frozenset({"1d"}),
                credential_state="placeholder",
                live_check_suitable=False,
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
        """Return an explicit deterministic failure until the adapter is implemented."""

        return self._unavailable_failure()

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        """Return an explicit deterministic failure until the adapter is implemented."""

        return self._unavailable_failure()

    def health_check(self) -> ProviderResult[str]:
        """Report placeholder status without requiring credentials or network I/O."""

        return ProviderResult.success(
            provider=self.name,
            data=f"unavailable until {self.display_name} integration is implemented/configured",
        )

    def _unavailable_failure(self) -> ProviderResult[Any]:
        return ProviderResult.failure(
            provider=self.name,
            error=(
                f"{self.display_name} provider is a placeholder; "
                "integration is not implemented or configured"
            ),
        )


@dataclass(frozen=True)
class PolygonProvider(PlaceholderEnhancedProvider):
    """Offline placeholder for a future Polygon.io provider adapter."""

    name: str = "polygon"
    display_name: str = "Polygon"


@dataclass(frozen=True)
class TwelveDataProvider(PlaceholderEnhancedProvider):
    """Offline placeholder for a future Twelve Data provider adapter."""

    name: str = "twelve-data"
    display_name: str = "Twelve Data"


def default_provider_registry() -> ProviderRegistry:
    """Return the safe default provider registry for local CLI commands."""

    return ProviderRegistry(
        (
            FmpProvider(),
            LocalFixtureProvider(),
            PolygonProvider(),
            StooqProvider(),
            TwelveDataProvider(),
            YFinanceProvider(),
        )
    )
