from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, cast
from urllib.error import HTTPError

import pytest
import signaldesk_backend.providers as providers_module
from signaldesk_backend import (
    Candle,
    CatalystContext,
    CatalystEvent,
    FallbackProvider,
    FmpProvider,
    FundamentalContext,
    LocalCsvProvider,
    LocalFixtureProvider,
    PolygonProvider,
    ProviderCapability,
    ProviderRegistry,
    ProviderResult,
    Quote,
    StooqProvider,
    Symbol,
    TwelveDataProvider,
    YFinanceProvider,
    default_provider_registry,
    fallback_provider_call,
    normalize_provider_name,
    provider_rate_limit_failure,
    redact_provider_diagnostic,
    resolve_provider_mode,
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


class FakeStooqResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "FakeStooqResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FakeStooqUrlopen:
    def __init__(self, body: bytes) -> None:
        self.body = body
        self.request_url: str | None = None
        self.timeout: float | None = None

    def __call__(self, request: object, *, timeout: float) -> FakeStooqResponse:
        self.request_url = cast(Any, request).full_url
        self.timeout = timeout
        return FakeStooqResponse(self.body)


class ExplodingStooqUrlopen:
    def __call__(self, request: object, *, timeout: float) -> FakeStooqResponse:
        raise TimeoutError("network timeout detail")


class RateLimitedStooqUrlopen:
    def __call__(self, request: object, *, timeout: float) -> FakeStooqResponse:
        raise HTTPError(
            url=cast(Any, request).full_url,
            code=429,
            msg="Too Many Requests token=secret-token",
            hdrs=cast(Any, None),
            fp=None,
        )


class FakeFmpResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status

    def __enter__(self) -> "FakeFmpResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class FakeFmpUrlopen:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.body = body
        self.status = status
        self.request_url: str | None = None
        self.timeout: float | None = None

    def __call__(self, request: object, *, timeout: float) -> FakeFmpResponse:
        self.request_url = cast(Any, request).full_url
        self.timeout = timeout
        return FakeFmpResponse(self.body, status=self.status)


class ExplodingFmpUrlopen:
    def __call__(self, request: object, *, timeout: float) -> FakeFmpResponse:
        raise TimeoutError("secret transport detail")


class RecordingProvider(FakeProvider):
    def __init__(self, name: str, *, fail: bool) -> None:
        super().__init__(name)
        self.fail = fail
        self.quote_calls = 0
        self.candle_calls = 0

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        self.candle_calls += 1
        if self.fail:
            return ProviderResult.failure(provider=self.name, error=f"{self.name} unavailable")
        return super().get_historical_candles(symbol, start=start, end=end, interval=interval)

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        self.quote_calls += 1
        if self.fail:
            return ProviderResult.failure(provider=self.name, error=f"{self.name} rate limited")
        return super().get_quote(symbol)


class RaisingQuoteProvider(FakeProvider):
    exception: Exception
    quote_calls: int

    def __init__(self, name: str, exception: Exception) -> None:
        super().__init__(name)
        object.__setattr__(self, "exception", exception)
        object.__setattr__(self, "quote_calls", 0)

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        object.__setattr__(self, "quote_calls", self.quote_calls + 1)
        raise self.exception


class FakeHistory:
    empty = False

    def iterrows(self) -> tuple[tuple[datetime, dict[str, float]], ...]:
        return (
            (
                NOW,
                {
                    "Open": 100.0,
                    "High": 102.0,
                    "Low": 99.0,
                    "Close": 101.5,
                    "Volume": 12345.0,
                },
            ),
        )


class EmptyHistory(FakeHistory):
    empty = True


class FakeYFinanceTicker:
    def __init__(self, ticker: str) -> None:
        self.ticker = ticker
        self.fast_info = {"last_price": 101.5, "bid": 101.0, "ask": 102.0}
        self.info: dict[str, float] = {}

    def history(self, *, start: datetime, end: datetime, interval: str) -> FakeHistory:
        return FakeHistory()


class EmptyYFinanceTicker(FakeYFinanceTicker):
    fast_info: dict[str, float] = {}

    def __init__(self, ticker: str) -> None:
        self.ticker = ticker
        self.fast_info = {}
        self.info = {}

    def history(self, *, start: datetime, end: datetime, interval: str) -> EmptyHistory:
        return EmptyHistory()


class ExplodingYFinanceTicker(FakeYFinanceTicker):
    def history(self, *, start: datetime, end: datetime, interval: str) -> FakeHistory:
        raise RuntimeError("network failure detail")


class FakeYFinanceModule:
    def Ticker(self, ticker: str) -> FakeYFinanceTicker:
        return FakeYFinanceTicker(ticker)


class EmptyYFinanceModule:
    def Ticker(self, ticker: str) -> EmptyYFinanceTicker:
        return EmptyYFinanceTicker(ticker)


class ExplodingYFinanceModule:
    def Ticker(self, ticker: str) -> ExplodingYFinanceTicker:
        return ExplodingYFinanceTicker(ticker)


def test_normalize_provider_name_canonicalizes_registry_keys() -> None:
    assert normalize_provider_name("  Fixture Provider  ") == "fixture provider"


@pytest.mark.parametrize("name", ["", "   "])
def test_normalize_provider_name_rejects_blank_names(name: str) -> None:
    with pytest.raises(ValueError, match="provider name"):
        normalize_provider_name(name)


def test_redact_provider_diagnostic_redacts_query_credentials() -> None:
    diagnostic = "GET https://example.test/path?apikey=abc123&symbol=AMD failed"

    redacted = redact_provider_diagnostic(diagnostic)

    assert "abc123" not in redacted
    assert "https://example.test/path" in redacted
    assert "apikey=<redacted>" in redacted
    assert "symbol=AMD" in redacted


def test_redact_provider_diagnostic_redacts_mixed_case_query_credentials() -> None:
    diagnostic = (
        "https://example.test/path?Access_Token=secret-token&Password=hunter2&symbol=AMD"
    )

    redacted = redact_provider_diagnostic(diagnostic)

    assert "secret-token" not in redacted
    assert "hunter2" not in redacted
    assert "Access_Token=<redacted>" in redacted
    assert "Password=<redacted>" in redacted
    assert "symbol=AMD" in redacted


def test_redact_provider_diagnostic_redacts_inline_token_substrings() -> None:
    diagnostic = "transport failed: token=abc123 api_key: secret456 password hunter2"

    redacted = redact_provider_diagnostic(diagnostic)

    assert "abc123" not in redacted
    assert "secret456" not in redacted
    assert "hunter2" not in redacted
    assert "token=<redacted>" in redacted
    assert "api_key: <redacted>" in redacted
    assert "password <redacted>" in redacted


def test_redact_provider_diagnostic_redacts_common_http_credential_forms() -> None:
    diagnostic = (
        "GET https://user:pass@example.test/path?symbol=AMD failed "
        "with X-API-Key: header-secret"
    )

    redacted = redact_provider_diagnostic(diagnostic)

    assert "user:pass" not in redacted
    assert "header-secret" not in redacted
    assert "https://<redacted>@example.test/path?symbol=AMD" in redacted
    assert "X-API-Key: <redacted>" in redacted


def test_provider_rate_limit_failure_uses_stable_redacted_diagnostic() -> None:
    result = provider_rate_limit_failure(
        "fmp",
        "GET https://example.test/quote?apikey=abc123&symbol=AMD token=secret-token",
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.startswith("fmp request was rate limited")
    assert "abc123" not in result.error
    assert "secret-token" not in result.error
    assert "apikey=<redacted>" in result.error
    assert "token=<redacted>" in result.error


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


def test_fallback_provider_call_returns_first_success_after_failures() -> None:
    result = fallback_provider_call(
        (
            lambda: ProviderResult.failure(provider="primary", error="primary unavailable"),
            lambda: ProviderResult.success(provider="backup", data="quote data"),
        )
    )

    assert result == ProviderResult.success(provider="backup", data="quote data")


def test_fallback_provider_does_not_call_later_providers_after_success() -> None:
    first = RecordingProvider("primary", fail=False)
    second = RecordingProvider("backup", fail=False)
    provider = FallbackProvider((first, second))

    result = provider.get_quote(Symbol("amd"))

    assert result.ok is True
    assert result.provider == "primary"
    assert first.quote_calls == 1
    assert second.quote_calls == 0


def test_fallback_provider_continues_after_raised_exception() -> None:
    first = RaisingQuoteProvider("primary", TimeoutError("primary token=secret-token timed out"))
    second = RecordingProvider("backup", fail=False)
    provider = FallbackProvider((first, second))

    result = provider.get_quote(Symbol("amd"))

    assert result.ok is True
    assert result.provider == "backup"
    assert first.quote_calls == 1
    assert second.quote_calls == 1


def test_fallback_provider_reports_raised_exceptions_with_redacted_provenance() -> None:
    first = RaisingQuoteProvider(
        "primary", RuntimeError("GET https://example.test/quote?apikey=secret-key failed")
    )
    provider = FallbackProvider((first,), name="equity-fallback")

    result = provider.get_quote(Symbol("amd"))

    assert result.ok is False
    assert result.provider == "equity-fallback"
    assert result.error is not None
    assert "secret-key" not in result.error
    assert result.warnings == (
        "primary: RuntimeError: GET https://example.test/quote?apikey=<redacted> failed",
    )


def test_fallback_provider_reports_all_failures_with_provenance() -> None:
    first = RecordingProvider("primary", fail=True)
    second = RecordingProvider("backup", fail=True)
    provider = FallbackProvider((first, second), name="equity-fallback")

    result = provider.get_quote(Symbol("amd"))

    assert result == ProviderResult.failure(
        provider="equity-fallback",
        error="all providers failed: primary: primary rate limited; backup: backup rate limited",
        warnings=("primary: primary rate limited", "backup: backup rate limited"),
    )
    assert first.quote_calls == 1
    assert second.quote_calls == 1


def test_fallback_provider_redacts_failure_provenance() -> None:
    result: ProviderResult[str] = fallback_provider_call(
        (
            lambda: ProviderResult.failure(
                provider="primary",
                error="GET https://example.test/quote?apikey=secret-key token=secret-token",
            ),
        )
    )

    assert result.ok is False
    assert result.error is not None
    assert "secret-key" not in result.error
    assert "secret-token" not in result.error
    assert result.warnings == (
        "primary: GET https://example.test/quote?apikey=<redacted> token=<redacted>",
    )


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

    assert registry.names() == (
        "fmp",
        "local-fixture",
        "polygon",
        "stooq",
        "twelve-data",
        "yfinance",
    )
    health = registry.get("local-fixture").health_check()
    assert health == ProviderResult.success(
        provider="local-fixture",
        data="ready (deterministic historical candles; no external credentials required)",
    )


def test_resolve_provider_mode_defaults_to_yfinance_price_role() -> None:
    provider_mode, unavailable_context = resolve_provider_mode(default_provider_registry())

    assert provider_mode.mode == "default"
    assert provider_mode.price_provider == "yfinance"
    assert provider_mode.fundamentals_provider is None
    assert provider_mode.catalyst_provider is None
    assert unavailable_context == ()


def test_resolve_provider_mode_falls_back_to_local_fixture_price_role(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    registry = ProviderRegistry((LocalFixtureProvider(),))

    default_mode, default_unavailable = resolve_provider_mode(registry)
    enhanced_mode, enhanced_unavailable = resolve_provider_mode(registry, mode="enhanced")

    assert default_mode.price_provider == "local-fixture"
    assert default_unavailable == ()
    assert enhanced_mode.price_provider == "local-fixture"
    assert enhanced_unavailable[0].context_type == "enhanced_price"
    assert enhanced_unavailable[0].reason.endswith("default local-fixture price provider")


def test_resolve_provider_mode_reports_missing_enhanced_context_without_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    provider_mode, unavailable_context = resolve_provider_mode(
        default_provider_registry(), mode="enhanced"
    )

    assert provider_mode.mode == "enhanced"
    assert provider_mode.price_provider == "yfinance"
    assert provider_mode.fundamentals_provider is None
    assert provider_mode.catalyst_provider is None
    assert tuple(item.context_type for item in unavailable_context) == (
        "enhanced_price",
        "fundamentals",
        "catalyst",
    )
    assert all(item.provider == "fmp" for item in unavailable_context)
    assert all("credentials are not configured" in item.reason for item in unavailable_context)


def test_resolve_provider_mode_uses_fmp_roles_when_configured() -> None:
    provider_mode, unavailable_context = resolve_provider_mode(
        ProviderRegistry((FmpProvider(api_key="test-key"), YFinanceProvider(_module=None))),
        mode="enhanced",
    )

    assert provider_mode.mode == "enhanced"
    assert provider_mode.price_provider == "fmp"
    assert provider_mode.fundamentals_provider == "fmp"
    assert provider_mode.catalyst_provider == "fmp"
    assert unavailable_context == ()


def test_resolve_provider_mode_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="mode must be default or enhanced"):
        resolve_provider_mode(default_provider_registry(), mode="paid")


def test_local_fixture_provider_returns_deterministic_daily_candles() -> None:
    provider = LocalFixtureProvider()
    symbol = Symbol("AMD")
    start = datetime(2026, 1, 1, tzinfo=UTC)
    end = datetime(2026, 3, 1, 12, tzinfo=UTC)

    capabilities = provider.capabilities()
    result = provider.get_historical_candles(symbol, start=start, end=end, interval="1d")

    assert capabilities == (
        ProviderCapability(
            provider="local-fixture",
            supports_realtime=False,
            supports_historical=True,
            supported_asset_classes=frozenset({"equity", "fixture"}),
            supported_intervals=frozenset({"1d"}),
            credential_state="not_required",
            live_check_suitable=True,
        ),
    )
    assert result.ok is True
    assert result.data is not None
    assert len(result.data) == 60
    assert result.data[0] == Candle(
        symbol=symbol,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("98"),
        close=Decimal("101"),
        volume=10_000,
    )
    assert result.data[-1] == Candle(
        symbol=symbol,
        timestamp=datetime(2026, 3, 1, tzinfo=UTC),
        open=Decimal("159"),
        high=Decimal("161"),
        low=Decimal("157"),
        close=Decimal("160"),
        volume=10_059,
    )


def test_local_fixture_provider_filters_dates_and_rejects_invalid_requests() -> None:
    provider = LocalFixtureProvider()
    symbol = Symbol("AMD")
    start = datetime(2026, 2, 27, 12, tzinfo=UTC)
    end = datetime(2026, 3, 1, 12, tzinfo=UTC)

    filtered = provider.get_historical_candles(symbol, start=start, end=end, interval="1d")
    unsupported_interval = provider.get_historical_candles(
        symbol, start=start, end=end, interval="1h"
    )
    reversed_dates = provider.get_historical_candles(symbol, start=end, end=start, interval="1d")

    assert filtered.ok is True
    assert filtered.data is not None
    assert [candle.timestamp for candle in filtered.data] == [
        datetime(2026, 2, 27, tzinfo=UTC),
        datetime(2026, 2, 28, tzinfo=UTC),
        datetime(2026, 3, 1, tzinfo=UTC),
    ]
    assert unsupported_interval == ProviderResult.failure(
        provider="local-fixture",
        error="local fixture supports only daily historical intervals",
    )
    assert reversed_dates == ProviderResult.failure(
        provider="local-fixture",
        error="start must be before end",
    )


@pytest.mark.parametrize(
    ("provider", "provider_name", "display_name"),
    (
        (PolygonProvider(), "polygon", "Polygon"),
        (TwelveDataProvider(), "twelve-data", "Twelve Data"),
    ),
)
def test_enhanced_provider_placeholders_are_offline_and_explicit(
    provider: PolygonProvider | TwelveDataProvider,
    provider_name: str,
    display_name: str,
) -> None:
    capabilities = provider.capabilities()
    health = provider.health_check()
    quote = provider.get_quote(Symbol("amd"))
    candles = provider.get_historical_candles(Symbol("amd"), start=NOW, end=NOW, interval="1d")

    assert capabilities == (
        ProviderCapability(
            provider=provider_name,
            provider_tier="enhanced",
            supports_realtime=True,
            supports_historical=True,
            supported_asset_classes=frozenset({"equity", "etf", "index"}),
            supported_intervals=frozenset({"1d"}),
            credential_state="placeholder",
            live_check_suitable=False,
        ),
    )
    assert health == ProviderResult.success(
        provider=provider_name,
        data=f"unavailable until {display_name} integration is implemented/configured",
    )
    expected_failure: ProviderResult[object] = ProviderResult.failure(
        provider=provider_name,
        error=(
            f"{display_name} provider is a placeholder; "
            "integration is not implemented or configured"
        ),
    )
    assert quote == expected_failure
    assert candles == expected_failure


def test_fmp_provider_reports_capabilities_and_missing_key_safely(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)
    provider = FmpProvider(api_key=None)

    capabilities = provider.capabilities()
    health = provider.health_check()
    quote = provider.get_quote(Symbol("amd"))
    candles = provider.get_historical_candles(Symbol("amd"), start=NOW, end=NOW, interval="1d")

    assert tuple(capability.data_role for capability in capabilities) == (
        "price",
        "fundamentals",
        "catalyst",
    )
    assert all(capability.provider == "fmp" for capability in capabilities)
    assert capabilities[0].supports_realtime is True
    assert capabilities[0].supports_historical is True
    assert capabilities[0].supported_intervals == frozenset({"1d"})
    assert capabilities[1].supports_realtime is False
    assert capabilities[1].supports_historical is False
    assert capabilities[1].supported_intervals == frozenset()
    assert all(
        capability.credential_state == "not_configured" for capability in capabilities
    )
    assert all(capability.live_check_suitable is False for capability in capabilities)
    assert health == ProviderResult.success(
        provider="fmp", data="unavailable until FMP credentials are configured"
    )
    assert quote == ProviderResult.failure(
        provider="fmp", error="FMP credentials are not configured"
    )
    assert candles == ProviderResult.failure(
        provider="fmp", error="FMP credentials are not configured"
    )


def test_fmp_provider_reports_configured_credential_state() -> None:
    provider = FmpProvider(api_key="test-key")

    capabilities = provider.capabilities()

    assert tuple(capability.data_role for capability in capabilities) == (
        "price",
        "fundamentals",
        "catalyst",
    )
    assert all(capability.provider == "fmp" for capability in capabilities)
    assert all(capability.credential_state == "configured" for capability in capabilities)


def test_fmp_provider_translates_mocked_quote_and_candles() -> None:
    quote_opener = FakeFmpUrlopen(
        b'[{"symbol":"AMD","price":176.50,"timestamp":1760000000}]'
    )
    candle_opener = FakeFmpUrlopen(
        b'{"symbol":"AMD","historical":[{"date":"2026-01-14","open":100.00,'
        b'"high":102.50,"low":99.75,"close":101.25,"volume":123456},'
        b'{"date":"2026-01-13","open":99.00,"high":101.00,"low":98.00,'
        b'"close":100.00,"volume":1000}]}'
    )
    provider = FmpProvider(api_key="test-key", _urlopen=quote_opener, timeout_seconds=2.5)
    candle_provider = FmpProvider(api_key="test-key", _urlopen=candle_opener, timeout_seconds=2.5)
    symbol = Symbol("amd")

    quote = provider.get_quote(symbol)
    candles = candle_provider.get_historical_candles(
        symbol, start=datetime(2026, 1, 14, tzinfo=UTC), end=NOW, interval="daily"
    )

    assert quote.ok is True
    assert quote.data is not None
    assert quote.data.symbol == symbol
    assert quote.data.last == Decimal("176.50")
    assert quote_opener.request_url is not None
    assert "apikey=test-key" in quote_opener.request_url
    assert candles.ok is True
    assert candles.data is not None
    assert [candle.timestamp for candle in candles.data] == [
        datetime(2026, 1, 13, tzinfo=UTC),
        datetime(2026, 1, 14, tzinfo=UTC),
    ]
    assert candles.data == (
        Candle(
            symbol=symbol,
            timestamp=datetime(2026, 1, 13, tzinfo=UTC),
            open=Decimal("99.0"),
            high=Decimal("101.0"),
            low=Decimal("98.0"),
            close=Decimal("100.0"),
            volume=1000,
        ),
        Candle(
            symbol=symbol,
            timestamp=datetime(2026, 1, 14, tzinfo=UTC),
            open=Decimal("100.0"),
            high=Decimal("102.5"),
            low=Decimal("99.75"),
            close=Decimal("101.25"),
            volume=123456,
        ),
    )


def test_fmp_provider_translates_mocked_fundamental_context() -> None:
    opener = FakeFmpUrlopen(
        b'[{"symbol":"AMD","companyName":"Advanced Micro Devices, Inc.",'
        b'"exchangeShortName":"NASDAQ","industry":"Semiconductors",'
        b'"sector":"Technology","mktCap":289000000000,"price":176.5,'
        b'"beta":1.84,"pe":45.2,"eps":3.91,'
        b'"currency":"USD","website":"https://www.amd.com"}]'
    )
    provider = FmpProvider(api_key="test-key", _urlopen=opener, timeout_seconds=2.5)
    symbol = Symbol("amd")

    result = provider.get_fundamental_context(symbol)

    assert result.ok is True
    assert result.data is not None
    assert result.data == FundamentalContext(
        symbol=symbol,
        provider="fmp",
        generated_at=result.data.generated_at,
        company_name="Advanced Micro Devices, Inc.",
        exchange="NASDAQ",
        industry="Semiconductors",
        sector="Technology",
        market_cap=289000000000,
        currency="USD",
        price=Decimal("176.5"),
        beta=Decimal("1.84"),
        pe_ratio=Decimal("45.2"),
        eps=Decimal("3.91"),
        source_url="https://www.amd.com",
    )
    assert opener.request_url is not None
    assert "profile/AMD" in opener.request_url
    assert "apikey=test-key" in opener.request_url


def test_fmp_provider_translates_mocked_catalyst_context() -> None:
    opener = FakeFmpUrlopen(
        b'[{"symbol":"AMD","publishedDate":"2026-01-15 13:45:00",'
        b'"title":"AMD announces data center accelerator update",'
        b'"site":"Example Wire","url":"https://example.test/amd-news",'
        b'"text":"Provider supplied article summary."},'
        b'{"symbol":"AMD","publishedDate":"invalid-date","title":"   "}]'
    )
    provider = FmpProvider(api_key="test-key", _urlopen=opener, timeout_seconds=2.5)
    symbol = Symbol("amd")

    result = provider.get_catalyst_context(symbol)

    assert result.ok is True
    assert result.data is not None
    assert result.data == CatalystContext(
        symbol=symbol,
        provider="fmp",
        generated_at=result.data.generated_at,
        events=(
            CatalystEvent(
                headline="AMD announces data center accelerator update",
                provider="fmp",
                published_at=datetime(2026, 1, 15, 13, 45, tzinfo=UTC),
                source="Example Wire",
                url="https://example.test/amd-news",
                summary="Provider supplied article summary.",
            ),
        ),
    )
    assert opener.request_url is not None
    assert "stock_news" in opener.request_url
    assert "tickers=AMD" in opener.request_url
    assert "limit=10" in opener.request_url
    assert "apikey=test-key" in opener.request_url


def test_fmp_provider_reports_missing_or_invalid_fundamental_context_safely() -> None:
    missing_key = FmpProvider(api_key=None)
    empty = FmpProvider(api_key="test-key", _urlopen=FakeFmpUrlopen(b"[]"))
    invalid = FmpProvider(api_key="test-key", _urlopen=FakeFmpUrlopen(b'[{"mktCap":-1}]'))
    fractional = FmpProvider(api_key="test-key", _urlopen=FakeFmpUrlopen(b'[{"mktCap":1.9}]'))

    assert missing_key.get_fundamental_context(Symbol("amd")) == ProviderResult.failure(
        provider="fmp", error="FMP credentials are not configured"
    )
    assert empty.get_fundamental_context(Symbol("amd")) == ProviderResult.failure(
        provider="fmp", error="no fundamental context for AMD"
    )
    assert invalid.get_fundamental_context(Symbol("amd")) == ProviderResult.failure(
        provider="fmp", error="fmp fundamental data was invalid"
    )
    assert fractional.get_fundamental_context(Symbol("amd")) == ProviderResult.failure(
        provider="fmp", error="fmp fundamental data was invalid"
    )


def test_fmp_provider_reports_missing_or_invalid_catalyst_context_safely() -> None:
    missing_key = FmpProvider(api_key=None)
    empty = FmpProvider(api_key="test-key", _urlopen=FakeFmpUrlopen(b"[]"))
    malformed = FmpProvider(api_key="test-key", _urlopen=FakeFmpUrlopen(b"{}"))
    invalid_event = FmpProvider(
        api_key="test-key",
        _urlopen=FakeFmpUrlopen(b'[{"title":"Headline","publishedDate":123}]'),
    )

    assert missing_key.get_catalyst_context(Symbol("amd")) == ProviderResult.failure(
        provider="fmp", error="FMP credentials are not configured"
    )
    assert empty.get_catalyst_context(Symbol("amd")) == ProviderResult.failure(
        provider="fmp", error="no catalyst context for AMD"
    )
    assert malformed.get_catalyst_context(Symbol("amd")) == ProviderResult.failure(
        provider="fmp", error="fmp catalyst data was invalid"
    )
    assert invalid_event.get_catalyst_context(Symbol("amd")) == ProviderResult.failure(
        provider="fmp", error="fmp catalyst data was invalid"
    )


def test_fmp_provider_returns_safe_failures_for_errors() -> None:
    malformed = FmpProvider(api_key="test-key", _urlopen=FakeFmpUrlopen(b"{}"))
    limited = FmpProvider(api_key="test-key", _urlopen=FakeFmpUrlopen(b"{}", status=429))
    exploding = FmpProvider(api_key="test-key", _urlopen=ExplodingFmpUrlopen())

    assert malformed.get_quote(Symbol("amd")) == ProviderResult.failure(
        provider="fmp", error="fmp quote data was invalid"
    )
    assert limited.get_quote(Symbol("amd")) == ProviderResult.failure(
        provider="fmp", error="fmp request was rate limited"
    )
    result = exploding.get_quote(Symbol("amd"))
    assert result == ProviderResult.failure(provider="fmp", error="fmp request failed")
    assert "secret transport" not in (result.error or "")


def test_fmp_provider_redacts_rate_limited_http_error_diagnostic() -> None:
    class RateLimitedFmpUrlopen:
        def __call__(self, request: object, *, timeout: float) -> FakeFmpResponse:
            raise HTTPError(
                url=cast(Any, request).full_url,
                code=429,
                msg="Too Many Requests token=secret-token",
                hdrs=cast(Any, None),
                fp=None,
            )

    provider = FmpProvider(api_key="test-key", _urlopen=RateLimitedFmpUrlopen())

    result = provider.get_quote(Symbol("amd"))

    assert result.ok is False
    assert result.error is not None
    assert result.error.startswith("fmp request was rate limited")
    assert "test-key" not in result.error
    assert "secret-token" not in result.error
    assert "apikey=<redacted>" in result.error
    assert "token=<redacted>" in result.error


def test_local_csv_provider_loads_schema_and_filters_daily_candles(tmp_path: Path) -> None:
    csv_path = tmp_path / "candles.csv"
    csv_path.write_text(
        "Date,Open,High,Low,Close,Volume\n"
        "2026-01-13,99.00,101.00,98.00,100.00,1000\n"
        "2026-01-14,100.00,102.50,99.75,101.25,123456\n"
        "2026-01-15,101.25,103.00,100.50,102.75,2000\n",
        encoding="utf-8",
    )
    provider = LocalCsvProvider(csv_path)
    symbol = Symbol("amd")

    result = provider.get_historical_candles(
        symbol,
        start=datetime(2026, 1, 14, tzinfo=UTC),
        end=datetime(2026, 1, 14, 23, 59, tzinfo=UTC),
        interval="daily",
    )

    assert result.ok is True
    assert result.data == (
        Candle(
            symbol=symbol,
            timestamp=datetime(2026, 1, 14, tzinfo=UTC),
            open=Decimal("100.00"),
            high=Decimal("102.50"),
            low=Decimal("99.75"),
            close=Decimal("101.25"),
            volume=123456,
        ),
    )
    capability = provider.capabilities()[0]
    assert capability.supports_historical is True
    assert capability.supported_intervals == frozenset({"1d"})
    assert capability.credential_state == "not_required"
    assert capability.live_check_suitable is True
    assert provider.health_check() == ProviderResult.success(
        provider="local-csv",
        data="ready (local CSV file available; no external credentials required)",
    )


def test_local_csv_provider_reports_safe_failures(tmp_path: Path) -> None:
    missing_columns = tmp_path / "missing-columns.csv"
    invalid_row = tmp_path / "invalid-row.csv"
    empty_after_filter = tmp_path / "outside-window.csv"
    missing_columns.write_text("Date,Open,Close\n2026-01-14,100,101\n", encoding="utf-8")
    invalid_row.write_text(
        "Date,Open,High,Low,Close,Volume\n2026-01-14,100,not-a-price,99,101,10\n",
        encoding="utf-8",
    )
    empty_after_filter.write_text(
        "Date,Open,High,Low,Close,Volume\n2026-01-10,100,101,99,100,10\n",
        encoding="utf-8",
    )
    symbol = Symbol("missing")

    missing_path_result = LocalCsvProvider(tmp_path / "does-not-exist.csv").get_historical_candles(
        symbol, start=NOW, end=NOW, interval="1d"
    )
    missing_columns_result = LocalCsvProvider(missing_columns).get_historical_candles(
        symbol, start=NOW, end=NOW, interval="1d"
    )
    invalid_row_result = LocalCsvProvider(invalid_row).get_historical_candles(
        symbol, start=NOW, end=NOW, interval="1d"
    )
    empty_after_filter_result = LocalCsvProvider(empty_after_filter).get_historical_candles(
        symbol, start=NOW, end=NOW, interval="1d"
    )
    unsupported_interval_result = LocalCsvProvider(empty_after_filter).get_historical_candles(
        symbol, start=NOW, end=NOW, interval="5m"
    )
    quote_result = LocalCsvProvider(empty_after_filter).get_quote(symbol)

    assert missing_path_result == ProviderResult.failure(
        provider="local-csv", error="local csv file was not found"
    )
    assert missing_columns_result == ProviderResult.failure(
        provider="local-csv", error="local csv missing required columns"
    )
    assert invalid_row_result == ProviderResult.failure(
        provider="local-csv", error="local csv historical data was invalid"
    )
    assert empty_after_filter_result == ProviderResult.failure(
        provider="local-csv", error="no historical data for MISSING in local csv"
    )
    assert unsupported_interval_result == ProviderResult.failure(
        provider="local-csv", error="local csv supports only daily historical intervals"
    )
    assert quote_result == ProviderResult.failure(
        provider="local-csv", error="local csv quote retrieval is not supported"
    )


def test_stooq_provider_reports_historical_capabilities_without_network() -> None:
    provider = StooqProvider()

    capabilities = provider.capabilities()
    health = provider.health_check()
    quote = provider.get_quote(Symbol("amd"))

    assert capabilities[0].provider == "stooq"
    assert capabilities[0].supports_realtime is False
    assert capabilities[0].supports_historical is True
    assert "equity" in capabilities[0].supported_asset_classes
    assert capabilities[0].supported_intervals == frozenset({"1d", "1wk", "1mo"})
    assert capabilities[0].credential_state == "not_required"
    assert capabilities[0].live_check_suitable is False
    assert health == ProviderResult.success(
        provider="stooq",
        data=(
            "not checked (no external credentials required; "
            "network availability is verified only during candle fetches)"
        ),
    )
    assert quote == ProviderResult.failure(
        provider="stooq", error="stooq quote retrieval is not supported"
    )


def test_stooq_provider_translates_csv_history() -> None:
    csv_body = (
        b"Date,Open,High,Low,Close,Volume\n"
        b"2026-01-14,100.00,102.50,99.75,101.25,123456\n"
    )
    opener = FakeStooqUrlopen(csv_body)
    provider = StooqProvider(_urlopen=opener, timeout_seconds=3.5)
    symbol = Symbol("amd")

    result = provider.get_historical_candles(symbol, start=NOW, end=NOW, interval="1d")

    assert result.ok is True
    assert result.data == (
        Candle(
            symbol=symbol,
            timestamp=datetime(2026, 1, 14, tzinfo=UTC),
            open=Decimal("100.00"),
            high=Decimal("102.50"),
            low=Decimal("99.75"),
            close=Decimal("101.25"),
            volume=123456,
        ),
    )
    assert opener.timeout == 3.5
    assert opener.request_url is not None
    assert "s=amd.us" in opener.request_url
    assert "i=d" in opener.request_url


def test_stooq_provider_handles_unavailable_and_malformed_responses() -> None:
    unavailable = StooqProvider(_urlopen=FakeStooqUrlopen(b"No data"))
    malformed = StooqProvider(_urlopen=FakeStooqUrlopen(b"not,candle,data\n1,2,3\n"))
    exploding = StooqProvider(_urlopen=ExplodingStooqUrlopen())
    symbol = Symbol("missing")

    unavailable_result = unavailable.get_historical_candles(
        symbol, start=NOW, end=NOW, interval="1d"
    )
    malformed_result = malformed.get_historical_candles(symbol, start=NOW, end=NOW, interval="1d")
    exploding_result = exploding.get_historical_candles(symbol, start=NOW, end=NOW, interval="1d")

    assert unavailable_result == ProviderResult.failure(
        provider="stooq", error="no historical data for MISSING"
    )
    assert malformed_result == ProviderResult.failure(
        provider="stooq", error="stooq historical data was invalid"
    )
    assert exploding_result == ProviderResult.failure(
        provider="stooq", error="stooq historical fetch failed"
    )
    assert "network timeout" not in (exploding_result.error or "")


def test_stooq_provider_classifies_rate_limited_http_errors() -> None:
    provider = StooqProvider(_urlopen=RateLimitedStooqUrlopen())

    result = provider.get_historical_candles(Symbol("amd"), start=NOW, end=NOW, interval="1d")

    assert result.ok is False
    assert result.error is not None
    assert result.error.startswith("stooq request was rate limited")
    assert "secret-token" not in result.error
    assert "token=<redacted>" in result.error


def test_stooq_provider_rejects_unsupported_intervals_before_network() -> None:
    opener = FakeStooqUrlopen(b"")
    provider = StooqProvider(_urlopen=opener)

    result = provider.get_historical_candles(Symbol("amd"), start=NOW, end=NOW, interval="5m")

    assert result == ProviderResult.failure(
        provider="stooq",
        error="stooq supports only daily, weekly, and monthly historical intervals",
    )
    assert opener.request_url is None


def test_yfinance_provider_reports_capabilities_without_importing_dependency() -> None:
    provider = YFinanceProvider(_module=None)

    capabilities = provider.capabilities()

    assert capabilities[0].provider == "yfinance"
    assert capabilities[0].supports_realtime is True
    assert capabilities[0].supports_historical is True
    assert "equity" in capabilities[0].supported_asset_classes
    assert {"1d", "1wk", "1mo"}.issubset(capabilities[0].supported_intervals)
    assert capabilities[0].credential_state == "not_required"
    assert capabilities[0].live_check_suitable is False


def test_yfinance_provider_translates_history_and_quote_models() -> None:
    provider = YFinanceProvider(_module=FakeYFinanceModule())
    symbol = Symbol("amd")

    candles = provider.get_historical_candles(symbol, start=NOW, end=NOW, interval="1d")
    quote = provider.get_quote(symbol)

    assert candles.ok is True
    assert candles.data is not None
    assert candles.data == (
        Candle(
            symbol=symbol,
            timestamp=NOW,
            open=Decimal("100.0"),
            high=Decimal("102.0"),
            low=Decimal("99.0"),
            close=Decimal("101.5"),
            volume=12345,
        ),
    )
    assert quote.ok is True
    assert quote.data is not None
    assert quote.data.symbol == symbol
    assert quote.data.bid == Decimal("101.0")
    assert quote.data.ask == Decimal("102.0")
    assert quote.data.last == Decimal("101.5")


def test_yfinance_provider_handles_missing_dependency_without_crashing_imports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_import(module_name: str) -> None:
        raise ImportError(module_name)

    monkeypatch.setattr(providers_module, "import_module", fail_import)
    provider = YFinanceProvider(_module=None)

    result = provider.get_quote(Symbol("missing"))
    health = provider.health_check()

    assert result == ProviderResult.failure(
        provider="yfinance",
        error="optional dependency yfinance is not installed",
    )
    assert health == ProviderResult.success(
        provider="yfinance",
        data="unavailable until optional dependency yfinance is installed",
    )


def test_yfinance_provider_handles_empty_data_deterministically() -> None:
    provider = YFinanceProvider(_module=EmptyYFinanceModule())
    symbol = Symbol("unknown")

    candles = provider.get_historical_candles(symbol, start=NOW, end=NOW, interval="1d")
    quote = provider.get_quote(symbol)

    assert candles == ProviderResult.failure(
        provider="yfinance",
        error="no historical data for UNKNOWN",
    )
    assert quote == ProviderResult.failure(provider="yfinance", error="no quote data for UNKNOWN")


def test_yfinance_provider_sanitizes_provider_failures() -> None:
    provider = YFinanceProvider(_module=ExplodingYFinanceModule())

    result = provider.get_historical_candles(Symbol("amd"), start=NOW, end=NOW, interval="1d")

    assert result == ProviderResult.failure(
        provider="yfinance",
        error="yfinance historical fetch failed",
    )
    assert "network failure" not in (result.error or "")
