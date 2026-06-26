from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from signaldesk_backend import (
    CachedHistoricalCandleProvider,
    Candle,
    HistoricalCandleCacheKey,
    ProviderCapability,
    ProviderResponseCache,
    ProviderResult,
    Quote,
    Symbol,
)

NOW = datetime(2026, 1, 15, 14, 30, tzinfo=UTC)
START = datetime(2026, 1, 1, tzinfo=UTC)
END = datetime(2026, 1, 15, tzinfo=UTC)


def _candle(close: str = "100.50") -> Candle:
    return Candle(
        symbol=Symbol("AMD"),
        timestamp=START,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal(close),
        volume=1000,
    )


@dataclass
class CountingProvider:
    name: str = "fixture"
    calls: int = 0
    fail: bool = False

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        return ()

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        self.calls += 1
        if self.fail:
            return ProviderResult.failure(
                provider=self.name, error="token=secret upstream unavailable"
            )
        return ProviderResult.success(provider=self.name, data=(_candle(),))

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        return ProviderResult.success(
            provider=self.name,
            data=Quote(symbol=symbol, timestamp=NOW, last=Decimal("100.50")),
        )

    def health_check(self) -> ProviderResult[str]:
        return ProviderResult.success(provider=self.name, data="healthy")


def test_historical_candle_cache_round_trips_by_provider_symbol_interval_range(
    tmp_path: Path,
) -> None:
    cache = ProviderResponseCache(tmp_path)
    key = HistoricalCandleCacheKey(
        provider="fixture",
        provider_mode="default",
        symbol=Symbol("AMD"),
        interval="1d",
        start=START,
        end=END,
    )
    cache.write_historical_candles(
        key,
        ProviderResult.success(provider="fixture", data=(_candle(),)),
        now=NOW,
    )

    result = cache.read_historical_candles(key, now=NOW)

    assert result is not None
    assert result.ok is True
    assert result.data == (_candle(),)
    assert "provider-cache: hit" in result.warnings



def test_cache_metadata_validation_uses_cache_id_normalization(tmp_path: Path) -> None:
    cache = ProviderResponseCache(tmp_path)
    mixed_case = HistoricalCandleCacheKey(
        provider="Fixture",
        provider_mode="Default",
        symbol=Symbol("AMD"),
        interval="1D",
        start=START,
        end=END,
        request_shape="Default",
    )
    normalized = HistoricalCandleCacheKey(
        provider="fixture",
        provider_mode="default",
        symbol=Symbol("AMD"),
        interval="1d",
        start=START,
        end=END,
        request_shape="default",
    )

    assert mixed_case.cache_id() == normalized.cache_id()

    cache.write_historical_candles(
        mixed_case,
        ProviderResult.success(provider="Fixture", data=(_candle(),)),
        now=NOW,
    )

    result = cache.read_historical_candles(normalized, now=NOW)

    assert result is not None
    assert result.ok is True
    assert "provider-cache: hit" in result.warnings

def test_cached_provider_reuses_success_without_calling_provider_again(tmp_path: Path) -> None:
    provider = CountingProvider()
    cached_provider = CachedHistoricalCandleProvider(
        provider=provider,
        cache=ProviderResponseCache(tmp_path),
        provider_mode="default",
    )

    first = cached_provider.get_historical_candles(
        Symbol("AMD"), start=START, end=END, interval="1d"
    )
    second = cached_provider.get_historical_candles(
        Symbol("AMD"), start=START, end=END, interval="1d"
    )

    assert first.ok is True
    assert second.ok is True
    assert provider.calls == 1
    assert second.warnings[0] == "provider-cache: hit"


def test_cached_provider_refresh_bypasses_existing_entry(tmp_path: Path) -> None:
    provider = CountingProvider()
    cached_provider = CachedHistoricalCandleProvider(
        provider=provider,
        cache=ProviderResponseCache(tmp_path),
        provider_mode="default",
    )
    refreshing_provider = CachedHistoricalCandleProvider(
        provider=provider,
        cache=ProviderResponseCache(tmp_path),
        provider_mode="default",
        refresh=True,
    )

    cached_provider.get_historical_candles(
        Symbol("AMD"), start=START, end=END, interval="1d"
    )
    refreshing_provider.get_historical_candles(Symbol("AMD"), start=START, end=END, interval="1d")

    assert provider.calls == 2


def test_cache_key_changes_with_provider_mode_date_range_request_shape_and_schema() -> None:
    base = HistoricalCandleCacheKey(
        provider="fixture",
        provider_mode="default",
        symbol=Symbol("AMD"),
        interval="1d",
        start=START,
        end=END,
    )
    enhanced = HistoricalCandleCacheKey(
        provider="fixture",
        provider_mode="enhanced",
        symbol=Symbol("AMD"),
        interval="1d",
        start=START,
        end=END,
    )
    later = HistoricalCandleCacheKey(
        provider="fixture",
        provider_mode="default",
        symbol=Symbol("AMD"),
        interval="1d",
        start=START + timedelta(days=1),
        end=END,
    )
    shaped = HistoricalCandleCacheKey(
        provider="fixture",
        provider_mode="default",
        symbol=Symbol("AMD"),
        interval="1d",
        start=START,
        end=END,
        request_shape="adjusted",
    )
    v2_schema = HistoricalCandleCacheKey(
        provider="fixture",
        provider_mode="default",
        symbol=Symbol("AMD"),
        interval="1d",
        start=START,
        end=END,
        adapter_schema_version="historical_candles.v2",
    )

    assert base.cache_id() != enhanced.cache_id()
    assert base.cache_id() != later.cache_id()
    assert base.cache_id() != shaped.cache_id()
    assert base.cache_id() != v2_schema.cache_id()


def test_cached_provider_failure_remains_explicit_unavailable_context_shape(
    tmp_path: Path,
) -> None:
    provider = CountingProvider(fail=True)
    cached_provider = CachedHistoricalCandleProvider(
        provider=provider,
        cache=ProviderResponseCache(tmp_path),
        provider_mode="default",
    )

    first = cached_provider.get_historical_candles(
        Symbol("AMD"), start=START, end=END, interval="1d"
    )
    second = cached_provider.get_historical_candles(
        Symbol("AMD"), start=START, end=END, interval="1d"
    )

    assert first.ok is False
    assert second.ok is False
    assert provider.calls == 1
    assert "secret" not in (first.error or "")
    assert "token=<redacted>" in (first.error or "")
    assert "secret" not in (second.error or "")
    assert "token=<redacted>" in (second.error or "")
    assert "provider-cache: cached failure" in second.warnings
