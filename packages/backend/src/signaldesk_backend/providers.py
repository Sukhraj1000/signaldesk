"""Provider contracts, adapters, and registry for market-data providers."""

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from importlib import import_module
from typing import Any, Protocol, cast
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

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


def default_provider_registry() -> ProviderRegistry:
    """Return the safe default provider registry for local CLI commands."""

    return ProviderRegistry((LocalFixtureProvider(), StooqProvider(), YFinanceProvider()))
