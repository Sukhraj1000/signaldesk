import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import signaldesk_backend.providers as providers_module
import signaldesk_cli.main as cli_main
from pytest import MonkeyPatch
from signaldesk_backend import (
    Candle,
    ProviderCapability,
    ProviderRegistry,
    ProviderResult,
    Quote,
    Symbol,
)
from signaldesk_cli.main import (
    _format_provider_capabilities,
    _format_provider_health,
    _run_provider_health_checks,
    app,
)
from typer.testing import CliRunner


@dataclass(frozen=True)
class ExplodingProvider:
    name: str = "exploding"

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
        return ProviderResult.failure(provider=self.name, error="not implemented")

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        return ProviderResult.failure(provider=self.name, error="not implemented")

    def health_check(self) -> ProviderResult[str]:
        raise RuntimeError("secret detail should not be shown")


@dataclass(frozen=True)
class ExplodingCapabilitiesProvider(ExplodingProvider):
    name: str = "exploding-capabilities"

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        raise RuntimeError("secret capability detail should not be shown")


@dataclass(frozen=True)
class WorkingProvider:
    name: str = "working"

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        return (
            ProviderCapability(
                provider=self.name,
                supports_realtime=False,
                supports_historical=True,
                supported_asset_classes=frozenset({"fixture"}),
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
        candles = tuple(
            Candle(
                symbol=symbol,
                timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index),
                open=Decimal(index + 10),
                high=Decimal(index + 11),
                low=Decimal(index + 9),
                close=Decimal(index + 10),
                volume=1000 + index,
            )
            for index in range(40)
        )
        return ProviderResult.success(provider=self.name, data=candles)

    def get_quote(self, symbol: Symbol) -> ProviderResult[Quote]:
        return ProviderResult.failure(provider=self.name, error="not implemented")

    def health_check(self) -> ProviderResult[str]:
        return ProviderResult.success(provider=self.name, data="healthy")


@dataclass(frozen=True)
class FundamentalsCapabilityProvider(WorkingProvider):
    name: str = "fundamentals-provider"

    def capabilities(self) -> tuple[ProviderCapability, ...]:
        return (
            ProviderCapability(
                provider=self.name,
                data_role="fundamentals",
                supports_realtime=False,
                supports_historical=True,
                supported_asset_classes=frozenset({"equity"}),
                supported_intervals=frozenset({"1d"}),
                credential_state="required",
                live_check_suitable=False,
            ),
        )


@dataclass(frozen=True)
class SwingingProvider(WorkingProvider):
    name: str = "swinging"

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        candles = [
            Candle(
                symbol=symbol,
                timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index),
                open=Decimal("10"),
                high=Decimal("10"),
                low=Decimal("10"),
                close=Decimal("10"),
                volume=1000 + index,
            )
            for index in range(34)
        ]
        pattern = (
            ("10", "8.50", "9"),
            ("12.05", "9", "12"),
            ("11", "8", "8.50"),
            ("12", "9", "11"),
            ("10", "8.05", "9"),
            ("11", "9", "10"),
        )
        for offset, (high, low, close) in enumerate(pattern, start=34):
            candles.append(
                Candle(
                    symbol=symbol,
                    timestamp=datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=offset),
                    open=Decimal("10"),
                    high=Decimal(high),
                    low=Decimal(low),
                    close=Decimal(close),
                    volume=1000 + offset,
                )
            )
        return ProviderResult.success(provider=self.name, data=tuple(candles))


@dataclass(frozen=True)
class FailingHistoricalProvider(WorkingProvider):
    name: str = "failing-history"

    def get_historical_candles(
        self,
        symbol: Symbol,
        *,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> ProviderResult[tuple[Candle, ...]]:
        return ProviderResult.failure(
            provider=self.name,
            error="GET https://example.test/path?apikey=secret failed",
        )


def test_health_command() -> None:
    result = CliRunner().invoke(app, ["health"])

    assert result.exit_code == 0
    assert "SignalDesk is configured for local." in result.stdout


def test_providers_check_is_available_from_help() -> None:
    result = CliRunner().invoke(app, ["providers", "--help"])

    assert result.exit_code == 0
    assert "check" in result.stdout
    assert "list" in result.stdout
    assert "mode" in result.stdout


def test_providers_list_reports_yfinance_capabilities(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(app, ["providers", "list"])

    assert result.exit_code == 0
    assert (
        "provider\ttier\trole\trealtime\thistorical\tasset_classes\tintervals\tcredential_state\tlive_check"
        in result.stdout
    )
    assert (
        "local-fixture\tdefault\tprice\tfalse\ttrue\tequity,fixture\t1d\tnot_required\ttrue"
        in result.stdout
    )
    assert (
        "polygon\tenhanced\tprice\ttrue\ttrue\tequity,etf,index\t1d\tplaceholder\tfalse"
        in result.stdout
    )
    assert (
        "twelve-data\tenhanced\tprice\ttrue\ttrue\tequity,etf,index\t1d\tplaceholder\tfalse"
        in result.stdout
    )
    assert (
        "fmp\tenhanced\tprice\ttrue\ttrue\tequity,etf,index\t1d\tnot_configured\tfalse"
        in result.stdout
    )
    assert (
        "fmp\tenhanced\tfundamentals\tfalse\tfalse\tequity,etf,index\t\tnot_configured\tfalse"
        in result.stdout
    )
    assert (
        "fmp\tenhanced\tcatalyst\tfalse\tfalse\tequity,etf,index\t\tnot_configured\tfalse"
        in result.stdout
    )
    assert "yfinance\tdefault\tprice\ttrue\ttrue\tcrypto,equity,etf,index" in result.stdout
    assert "not_required\tfalse" in result.stdout


def test_providers_mode_resolves_default_price_role(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(app, ["providers", "mode"])

    assert result.exit_code == 0
    assert "role\tprovider" in result.stdout
    assert "mode\tdefault" in result.stdout
    assert "price\tyfinance" in result.stdout
    assert "fundamentals\tunavailable" in result.stdout
    assert "catalyst\tunavailable" in result.stdout


def test_providers_mode_json_reports_enhanced_unavailable_context(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(
        app, ["providers", "mode", "--mode", "enhanced", "--output", "json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["mode"] == "enhanced"
    assert payload["price_provider"] == "yfinance"
    assert payload["fundamentals_provider"] is None
    assert payload["catalyst_provider"] is None
    assert [item["context_type"] for item in payload["unavailable_context"]] == [
        "enhanced_price",
        "fundamentals",
        "catalyst",
    ]
    assert all(item["provider"] == "fmp" for item in payload["unavailable_context"])


def test_providers_list_json_reports_machine_readable_capabilities(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(app, ["providers", "list", "--output", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    capabilities = payload["providers"]
    assert {
        "provider": "local-fixture",
        "tier": "default",
        "role": "price",
        "realtime": False,
        "historical": True,
        "asset_classes": ["equity", "fixture"],
        "intervals": ["1d"],
        "credential_state": "not_required",
        "live_check": True,
    } in capabilities
    assert {
        "provider": "fmp",
        "tier": "enhanced",
        "role": "fundamentals",
        "realtime": False,
        "historical": False,
        "asset_classes": ["equity", "etf", "index"],
        "intervals": [],
        "credential_state": "not_configured",
        "live_check": False,
    } in capabilities
    assert any(
        capability["provider"] == "yfinance"
        and capability["tier"] == "default"
        and capability["role"] == "price"
        and capability["credential_state"] == "not_required"
        for capability in capabilities
    )


def test_providers_list_filters_capabilities_by_role_and_tier(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(
        app,
        ["providers", "list", "--role", "fundamentals", "--tier", "enhanced"],
    )

    assert result.exit_code == 0
    assert (
        "provider\ttier\trole\trealtime\thistorical\tasset_classes\tintervals\tcredential_state\tlive_check"
        in result.stdout
    )
    assert (
        "fmp\tenhanced\tfundamentals\tfalse\tfalse\tequity,etf,index\t\tnot_configured\tfalse"
        in result.stdout
    )
    assert "fmp\tenhanced\tprice" not in result.stdout
    assert "local-fixture" not in result.stdout
    assert "yfinance" not in result.stdout


def test_providers_list_json_filters_capabilities_by_default_tier(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(
        app, ["providers", "list", "--output", "json", "--tier", "default"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    capabilities = payload["providers"]
    assert capabilities
    assert all(capability["tier"] == "default" for capability in capabilities)
    assert {capability["provider"] for capability in capabilities} == {
        "local-fixture",
        "stooq",
        "yfinance",
    }


def test_providers_list_filters_by_credential_state_and_live_check_safety(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "providers",
            "list",
            "--credential-state",
            "not required",
            "--live-check-only",
        ],
    )

    assert result.exit_code == 0
    assert (
        "provider\ttier\trole\trealtime\thistorical\tasset_classes\tintervals\tcredential_state\tlive_check"
        in result.stdout
    )
    assert (
        "local-csv\tdefault\tprice\tfalse\ttrue\tcrypto,equity,etf,index\t1d\tnot_required\ttrue"
        not in result.stdout
    )
    assert (
        "local-fixture\tdefault\tprice\tfalse\ttrue\tequity,fixture\t1d\tnot_required\ttrue"
        in result.stdout
    )
    assert "stooq" not in result.stdout
    assert "yfinance" not in result.stdout
    assert "fmp" not in result.stdout


def test_providers_list_json_filters_by_credential_state(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.delenv("FMP_API_KEY", raising=False)

    result = CliRunner().invoke(
        app,
        [
            "providers",
            "list",
            "--output",
            "json",
            "--credential-state",
            "not_configured",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    capabilities = payload["providers"]
    assert capabilities
    assert all(
        capability["credential_state"] == "not_configured" for capability in capabilities
    )
    assert {capability["provider"] for capability in capabilities} == {"fmp"}
    assert {capability["role"] for capability in capabilities} == {
        "price",
        "fundamentals",
        "catalyst",
    }


def test_providers_list_rejects_unknown_output_format() -> None:
    result = CliRunner().invoke(app, ["providers", "list", "--output", "xml"])

    assert result.exit_code == 2
    assert "--output must be 'table' or 'json'." in result.stderr


def test_providers_check_reports_default_local_provider_without_secrets() -> None:
    result = CliRunner().invoke(app, ["providers", "check"])

    assert result.exit_code == 0
    assert "provider\tstatus\tresult" in result.stdout
    assert (
        "local-fixture\tok\tready (deterministic historical candles; "
        "no external credentials required)" in result.stdout
    )
    assert (
        "polygon\tok\tunavailable until Polygon integration is implemented/configured"
        in result.stdout
    )
    assert (
        "twelve-data\tok\tunavailable until Twelve Data integration is implemented/configured"
        in result.stdout
    )
    assert (
        "stooq\tok\tnot checked (no external credentials required; "
        "network availability is verified only during candle fetches)" in result.stdout
    )
    assert "API_KEY" not in result.stdout
    assert "TOKEN" not in result.stdout


def test_providers_check_live_check_only_uses_capability_safety() -> None:
    result = CliRunner().invoke(app, ["providers", "check", "--live-check-only"])

    assert result.exit_code == 0
    assert "provider\tstatus\tresult" in result.stdout
    assert (
        "local-fixture\tok\tready (deterministic historical candles; "
        "no external credentials required)" in result.stdout
    )
    assert "stooq" not in result.stdout
    assert "yfinance" not in result.stdout
    assert "fmp" not in result.stdout
    assert "polygon" not in result.stdout
    assert "twelve-data" not in result.stdout


def test_providers_check_json_live_check_only_reports_safe_subset() -> None:
    result = CliRunner().invoke(
        app, ["providers", "check", "--output", "json", "--live-check-only"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload == {
        "providers": [
            {
                "provider": "local-fixture",
                "status": "ok",
                "result": (
                    "ready (deterministic historical candles; "
                    "no external credentials required)"
                ),
                "warnings": [],
            }
        ]
    }


def test_ta_command_runs_against_default_local_fixture_without_network(
    monkeypatch: MonkeyPatch,
) -> None:
    def fail_on_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("local-fixture smoke path must not open network connections")

    monkeypatch.setattr(providers_module, "urlopen", fail_on_network)

    result = CliRunner().invoke(
        app,
        ["ta", "AMD", "--provider", "local-fixture", "--llm", "none", "--output", "json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["symbol"] == "AMD"
    assert payload["provider"] == "local-fixture"
    assert payload["candles"] == 60
    assert payload["provenance"] == [
        {
            "provider": "local-fixture",
            "source": "historical_candles",
            "timeframe": "1d",
            "inputs": ["AMD"],
            "observations": 60,
        }
    ]


def test_ta_command_runs_provider_to_indicator_bridge(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )

    result = CliRunner().invoke(
        app, ["ta", "AMD", "--provider", "working", "--llm", "none", "--output", "json"]
    )

    assert result.exit_code == 0
    assert '"symbol": "AMD"' in result.stdout
    assert '"provider": "working"' in result.stdout
    assert '"latest_close": "49"' in result.stdout
    assert '"sma_20"' in result.stdout
    assert '"rsi_14"' in result.stdout


def test_ta_command_defaults_to_yfinance_provider(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((WorkingProvider(name="yfinance"),)),
    )

    result = CliRunner().invoke(app, ["ta", "AMD", "--llm", "none", "--output", "json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["symbol"] == "AMD"
    assert payload["provider"] == "yfinance"
    assert payload["provenance"][0]["provider"] == "yfinance"


def test_ta_json_contract_has_explicit_fact_signal_risk_provenance_sections(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )

    result = CliRunner().invoke(
        app, ["ta", "AMD", "--provider", "working", "--llm", "none", "--output", "json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)

    expected = {
        "schema_version": "signaldesk.ta.v1",
        "symbol": "AMD",
        "provider": "working",
        "interval": "1d",
        "candles": 40,
        "latest_timestamp": "2024-02-09T00:00:00+00:00",
        "latest_close": "49",
        "sma_20": "39.5",
        "ema_20": "39.50000000000000000000000000",
        "rsi_14": "100",
        "macd": "7.00000000000000000000000000",
        "macd_signal": "7.000000000000000000000000000",
        "macd_histogram": "0E-27",
        "atr_14": "2",
        "volume_average_20": "1029.5",
        "relative_volume_20": "1.010209042294603791929995139",
        "latest_swing_high": None,
        "latest_swing_low": None,
        "confirmation_level": None,
        "invalidation_level": None,
        "facts": {
            "symbol": "AMD",
            "provider": "working",
            "interval": "1d",
            "candles": 40,
            "latest_timestamp": "2024-02-09T00:00:00+00:00",
            "latest_close": "49",
        },
        "deterministic_signals": {
            "indicators": {
                "sma_20": "39.5",
                "ema_20": "39.50000000000000000000000000",
                "rsi_14": "100",
                "macd": "7.00000000000000000000000000",
                "macd_signal": "7.000000000000000000000000000",
                "macd_histogram": "0E-27",
                "atr_14": "2",
                "volume_average_20": "1029.5",
                "relative_volume_20": "1.010209042294603791929995139",
            },
            "swing_levels": {"latest_swing_high": None, "latest_swing_low": None},
            "setup_levels": {"confirmation_level": None, "invalidation_level": None},
        },
        "risks": [
            {
                "kind": "scope_limit",
                "severity": "info",
                "message": (
                    "This output contains deterministic technical analysis only; missing "
                    "enhanced context is reported as unavailable context, not as no risk."
                ),
            }
        ],
        "provenance": [
            {
                "provider": "working",
                "source": "historical_candles",
                "timeframe": "1d",
                "inputs": ["AMD"],
                "observations": 40,
            }
        ],
        "unavailable_context": [
            {
                "context_type": "fundamentals",
                "reason": "not available in the default technical-analysis CLI path",
                "provider": "working",
            },
            {
                "context_type": "llm_narrative",
                "reason": "--llm none selected; narrative explanations are disabled",
                "provider": None,
            },
        ],
        "llm": "none",
        "narrative": None,
    }
    assert payload == expected


def test_ta_table_output_stays_flat_when_json_contract_sections_are_added(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )

    result = CliRunner().invoke(app, ["ta", "AMD", "--provider", "working", "--llm", "none"])

    assert result.exit_code == 0
    assert "schema_version\tsignaldesk.ta.v1" in result.stdout
    assert "symbol\tAMD" in result.stdout
    assert "latest_close\t49" in result.stdout
    assert "facts\t" not in result.stdout
    assert "deterministic_signals\t" not in result.stdout
    assert "unavailable_context\t" not in result.stdout


def test_ta_command_includes_traceable_confirmation_and_invalidation_levels(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((SwingingProvider(),))
    )

    result = CliRunner().invoke(
        app, ["ta", "AMD", "--provider", "swinging", "--llm", "none", "--output", "json"]
    )

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    confirmation = payload["confirmation_level"]
    invalidation = payload["invalidation_level"]

    assert confirmation is not None
    assert confirmation["kind"] == "confirmation"
    assert confirmation["price"] == "12.05"
    assert confirmation["source_rule"] == "nearest_resistance_above_latest_close"
    assert confirmation["source_level"] == "resistance_zone[12.05,12.05] touches=1"
    assert confirmation["reason"] == (
        "Latest close remains below this resistance zone; a move through it would "
        "confirm upside continuation."
    )
    assert invalidation is not None
    assert invalidation["kind"] == "invalidation"
    assert invalidation["price"] == "8"
    assert invalidation["source_rule"] == "nearest_support_below_latest_close"
    assert invalidation["source_level"] == "support_zone[8,8] touches=1"
    assert invalidation["reason"] == (
        "Latest close remains above this support zone; a break below it would "
        "invalidate the current technical setup."
    )


def test_ta_command_reports_provider_failures_without_secrets(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((FailingHistoricalProvider(),)),
    )

    result = CliRunner().invoke(app, ["ta", "AMD", "--provider", "failing-history"])

    assert result.exit_code == 1
    assert "apikey=<redacted>" in result.stderr
    assert "secret" not in result.stderr


def test_ta_command_rejects_llm_modes_until_guardrails_exist() -> None:
    result = CliRunner().invoke(app, ["ta", "AMD", "--llm", "openai"])

    assert result.exit_code == 2
    assert "Only --llm none is currently supported." in result.stderr


def test_ta_command_reports_validation_errors(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_main, "default_provider_registry", lambda: ProviderRegistry((WorkingProvider(),))
    )

    unknown_provider = CliRunner().invoke(app, ["ta", "AMD", "--provider", "missing"])
    invalid_symbol = CliRunner().invoke(app, ["ta", "bad symbol", "--provider", "working"])

    assert unknown_provider.exit_code == 2
    assert "provider not registered: missing" in unknown_provider.stderr
    assert invalid_symbol.exit_code == 2
    assert "ticker must not contain whitespace" in invalid_symbol.stderr


def test_provider_health_formatter_reports_failure_status() -> None:
    line = _format_provider_health(
        "broken",
        ProviderResult.failure(provider="broken", error="unavailable without configured adapter"),
    )

    assert line == "broken\tfailed\tunavailable without configured adapter"


def test_provider_health_formatter_redacts_credential_diagnostics() -> None:
    line = _format_provider_health(
        "broken",
        ProviderResult.failure(
            provider="broken",
            error="GET https://example.test/path?apikey=abc123&symbol=AMD failed",
        ),
    )

    assert "abc123" not in line
    assert line == (
        "broken\tfailed\tGET https://example.test/path?apikey=<redacted>&symbol=AMD failed"
    )


def test_provider_capability_formatter_reports_registry_capabilities() -> None:
    lines = _format_provider_capabilities(ProviderRegistry((ExplodingProvider(),)))

    assert lines == (
        "provider\ttier\trole\trealtime\thistorical\tasset_classes\tintervals\tcredential_state\tlive_check",
        "exploding\tunknown\tunknown\tfalse\tfalse\t\t\tunknown\tfalse",
    )


def test_provider_capability_formatter_uses_declared_data_role() -> None:
    lines = _format_provider_capabilities(ProviderRegistry((FundamentalsCapabilityProvider(),)))

    assert lines == (
        "provider\ttier\trole\trealtime\thistorical\tasset_classes\tintervals\tcredential_state\tlive_check",
        "fundamentals-provider\tdefault\tfundamentals\tfalse\ttrue\tequity\t1d\trequired\tfalse",
    )


def test_providers_list_continues_when_capabilities_raise(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((ExplodingCapabilitiesProvider(), ExplodingProvider())),
    )

    result = CliRunner().invoke(app, ["providers", "list"])

    assert result.exit_code == 0
    assert (
        "exploding-capabilities\tunknown\tunknown\tfalse\tfalse\t\t\tunknown\tfalse"
        in result.stdout
    )
    assert "exploding\tunknown\tunknown\tfalse\tfalse\t\t\tunknown\tfalse" in result.stdout
    assert "secret capability detail" not in result.stdout


def test_provider_health_checks_convert_exceptions_to_sanitized_failures() -> None:
    exit_code, provider_statuses = _run_provider_health_checks(
        ProviderRegistry((ExplodingProvider(),))
    )

    assert exit_code == 1
    assert provider_statuses == (
        {
            "provider": "exploding",
            "status": "failed",
            "result": "health check raised an exception",
            "warnings": (),
        },
    )
    assert "secret detail" not in json.dumps(provider_statuses)


def test_providers_check_json_reports_sanitized_machine_readable_status(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((WorkingProvider(), ExplodingProvider())),
    )

    result = CliRunner().invoke(app, ["providers", "check", "--output", "json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload == {
        "providers": [
            {
                "provider": "exploding",
                "status": "failed",
                "result": "health check raised an exception",
                "warnings": [],
            },
            {
                "provider": "working",
                "status": "ok",
                "result": "healthy",
                "warnings": [],
            },
        ]
    }
    assert "secret detail" not in result.stdout


def test_providers_check_rejects_unknown_output_format() -> None:
    result = CliRunner().invoke(app, ["providers", "check", "--output", "xml"])

    assert result.exit_code == 2
    assert "--output must be 'table' or 'json'." in result.stderr
