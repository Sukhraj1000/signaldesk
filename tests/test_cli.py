from dataclasses import dataclass
from datetime import datetime

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


def test_health_command() -> None:
    result = CliRunner().invoke(app, ["health"])

    assert result.exit_code == 0
    assert "SignalDesk is configured for local." in result.stdout


def test_providers_check_is_available_from_help() -> None:
    result = CliRunner().invoke(app, ["providers", "--help"])

    assert result.exit_code == 0
    assert "check" in result.stdout
    assert "list" in result.stdout


def test_providers_list_reports_yfinance_capabilities() -> None:
    result = CliRunner().invoke(app, ["providers", "list"])

    assert result.exit_code == 0
    assert "provider\trealtime\thistorical\tasset_classes" in result.stdout
    assert "local-fixture\tfalse\tfalse\tfixture" in result.stdout
    assert "polygon\ttrue\ttrue\tequity,etf,index" in result.stdout
    assert "twelve-data\ttrue\ttrue\tequity,etf,index" in result.stdout
    assert "yfinance\ttrue\ttrue\tcrypto,equity,etf,index" in result.stdout


def test_providers_check_reports_default_local_provider_without_secrets() -> None:
    result = CliRunner().invoke(app, ["providers", "check"])

    assert result.exit_code == 0
    assert "provider\tstatus\tresult" in result.stdout
    assert "local-fixture\tok\tready (no external credentials required)" in result.stdout
    assert (
        "polygon\tok\tunavailable until Polygon integration is implemented/configured"
        in result.stdout
    )
    assert (
        "twelve-data\tok\tunavailable until Twelve Data integration is implemented/configured"
        in result.stdout
    )
    assert "API_KEY" not in result.stdout
    assert "TOKEN" not in result.stdout


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

    assert lines == ("provider\trealtime\thistorical\tasset_classes", "exploding\tfalse\tfalse\t")


def test_providers_list_continues_when_capabilities_raise(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(
        cli_main,
        "default_provider_registry",
        lambda: ProviderRegistry((ExplodingCapabilitiesProvider(), ExplodingProvider())),
    )

    result = CliRunner().invoke(app, ["providers", "list"])

    assert result.exit_code == 0
    assert "exploding-capabilities\tfalse\tfalse\t" in result.stdout
    assert "exploding\tfalse\tfalse\t" in result.stdout
    assert "secret capability detail" not in result.stdout


def test_provider_health_checks_convert_exceptions_to_sanitized_failures() -> None:
    exit_code, lines = _run_provider_health_checks(ProviderRegistry((ExplodingProvider(),)))

    assert exit_code == 1
    assert lines == (
        "provider\tstatus\tresult",
        "exploding\tfailed\thealth check raised an exception",
    )
    assert "secret detail" not in "\n".join(lines)
