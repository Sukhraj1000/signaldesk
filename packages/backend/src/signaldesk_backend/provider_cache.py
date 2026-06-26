'''Filesystem provider-response cache for deterministic market-data lookups.'''

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from signaldesk_backend.models import Candle, ProviderCapability, ProviderResult, Quote, Symbol
from signaldesk_backend.providers import MarketDataProvider, redact_provider_diagnostic

PROVIDER_CACHE_SCHEMA_VERSION = "signaldesk.provider_cache.v1"
ADAPTER_SCHEMA_VERSION = "historical_candles.v1"


@dataclass(frozen=True)
class HistoricalCandleCacheKey:
    '''Stable key inputs for cached historical candle provider responses.'''

    provider: str
    provider_mode: str
    symbol: Symbol
    interval: str
    start: datetime
    end: datetime
    request_shape: str = "default"
    adapter_schema_version: str = ADAPTER_SCHEMA_VERSION

    def cache_id(self) -> str:
        payload = {
            "adapter_schema_version": self.adapter_schema_version,
            "end": _cache_range_value(self.end, self.interval),
            "interval": self.interval.strip().lower(),
            "provider": self.provider.strip().lower(),
            "provider_mode": self.provider_mode.strip().lower(),
            "request_shape": self.request_shape.strip().lower(),
            "start": _cache_range_value(self.start, self.interval),
            "symbol": self.symbol.ticker,
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProviderResponseCache:
    '''Read/write JSON files for provider historical-candle responses.'''

    root: Path
    success_ttl: timedelta | None = None
    failure_ttl: timedelta | None = timedelta(minutes=15)

    def read_historical_candles(
        self, key: HistoricalCandleCacheKey, *, now: datetime | None = None
    ) -> ProviderResult[tuple[Candle, ...]] | None:
        path = self._path_for(key)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self._validate_metadata(payload, key)
            written_at = datetime.fromisoformat(str(payload["written_at"]))
            status = str(payload["status"])
            ttl = self.success_ttl if status == "success" else self.failure_ttl
            if ttl is not None and self._is_expired(written_at, ttl, now=now):
                return None
            warnings = tuple(str(item) for item in payload.get("warnings", ()))
            if status == "failure":
                error = redact_provider_diagnostic(payload.get("error", "cached provider failure"))
                return ProviderResult.failure(
                    provider=key.provider,
                    error=error,
                    warnings=("provider-cache: cached failure", *warnings),
                )
            candles = tuple(_candle_from_payload(item) for item in payload["candles"])
            return ProviderResult.success(
                provider=key.provider,
                data=candles,
                warnings=("provider-cache: hit", *warnings),
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            return None

    def write_historical_candles(
        self,
        key: HistoricalCandleCacheKey,
        result: ProviderResult[tuple[Candle, ...]],
        *,
        now: datetime | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "schema_version": PROVIDER_CACHE_SCHEMA_VERSION,
            "adapter_schema_version": key.adapter_schema_version,
            "provider": key.provider,
            "provider_mode": key.provider_mode,
            "symbol": key.symbol.ticker,
            "interval": key.interval,
            "start": _cache_range_value(key.start, key.interval),
            "end": _cache_range_value(key.end, key.interval),
            "request_shape": key.request_shape,
            "written_at": (now or datetime.now(UTC)).astimezone(UTC).isoformat(),
            "warnings": list(result.warnings),
        }
        if result.ok:
            payload.update(
                {
                    "status": "success",
                    "candles": [_candle_payload(candle) for candle in (result.data or ())],
                }
            )
        else:
            payload.update(
                {
                    "status": "failure",
                    "error": redact_provider_diagnostic(result.error or "provider failed"),
                }
            )
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        tmp_path.replace(path)

    def _path_for(self, key: HistoricalCandleCacheKey) -> Path:
        provider = _safe_path_part(key.provider)
        interval = _safe_path_part(key.interval)
        symbol = _safe_path_part(key.symbol.ticker)
        return (
            self.root
            / "historical-candles"
            / provider
            / interval
            / symbol
            / f"{key.cache_id()}.json"
        )

    def _validate_metadata(self, payload: dict[str, Any], key: HistoricalCandleCacheKey) -> None:
        expected = {
            "schema_version": PROVIDER_CACHE_SCHEMA_VERSION,
            "adapter_schema_version": key.adapter_schema_version,
            "provider": key.provider,
            "provider_mode": key.provider_mode,
            "symbol": key.symbol.ticker,
            "interval": key.interval,
            "start": _cache_range_value(key.start, key.interval),
            "end": _cache_range_value(key.end, key.interval),
            "request_shape": key.request_shape,
        }
        for field, value in expected.items():
            if payload.get(field) != value:
                raise ValueError(f"cache metadata mismatch: {field}")
        if payload.get("status") not in {"success", "failure"}:
            raise ValueError("cache status must be success or failure")

    @staticmethod
    def _is_expired(written_at: datetime, ttl: timedelta, *, now: datetime | None = None) -> bool:
        if written_at.tzinfo is None:
            written_at = written_at.replace(tzinfo=UTC)
        return (now or datetime.now(UTC)).astimezone(UTC) - written_at.astimezone(UTC) > ttl


@dataclass(frozen=True)
class CachedHistoricalCandleProvider:
    '''Market-data provider wrapper with filesystem caching for historical candles.'''

    provider: MarketDataProvider
    cache: ProviderResponseCache
    provider_mode: str
    refresh: bool = False
    cache_failures: bool = True

    @property
    def name(self) -> str:
        return self.provider.name

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        return self.provider.capabilities()

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        key = HistoricalCandleCacheKey(
            provider=self.provider.name,
            provider_mode=self.provider_mode,
            symbol=symbol,
            interval=interval,
            start=start,
            end=end,
        )
        if not self.refresh:
            cached = self.cache.read_historical_candles(key)
            if cached is not None:
                return cached
        result = self.provider.get_historical_candles(
            symbol, start=start, end=end, interval=interval
        )
        if result.ok or self.cache_failures:
            self.cache.write_historical_candles(key, result)
        return result

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        return self.provider.get_quote(symbol)

    def health_check(self) -> ProviderResult[str]:
        return self.provider.health_check()


def _cache_range_value(value: datetime, interval: str) -> str:
    if interval.strip().lower() in {"1d", "1day", "1wk", "1mo"}:
        return value.astimezone(UTC).date().isoformat()
    return value.astimezone(UTC).replace(microsecond=0).isoformat()


def _safe_path_part(value: str) -> str:
    safe = "".join(character.lower() if character.isalnum() else "-" for character in value)
    return "-".join(part for part in safe.split("-") if part) or "unknown"


def _candle_payload(candle: Candle) -> dict[str, Any]:
    return {
        "symbol": {
            "ticker": candle.symbol.ticker,
            "exchange": candle.symbol.exchange,
            "asset_class": candle.symbol.asset_class,
            "currency": candle.symbol.currency,
        },
        "timestamp": candle.timestamp.astimezone(UTC).isoformat(),
        "open": str(candle.open),
        "high": str(candle.high),
        "low": str(candle.low),
        "close": str(candle.close),
        "volume": candle.volume,
    }


def _candle_from_payload(payload: dict[str, Any]) -> Candle:
    symbol_payload = payload["symbol"]
    return Candle(
        symbol=Symbol(
            ticker=str(symbol_payload["ticker"]),
            exchange=symbol_payload.get("exchange"),
            asset_class=str(symbol_payload.get("asset_class") or "equity"),
            currency=str(symbol_payload.get("currency") or "USD"),
        ),
        timestamp=datetime.fromisoformat(str(payload["timestamp"])),
        open=Decimal(str(payload["open"])),
        high=Decimal(str(payload["high"])),
        low=Decimal(str(payload["low"])),
        close=Decimal(str(payload["close"])),
        volume=int(payload["volume"]),
    )
