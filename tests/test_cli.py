from dataclasses import dataclass
from datetime import datetime

from signaldesk_backend import (
    Candle,
    ProviderCapability,
    ProviderRegistry,
    ProviderResult,
    Quote,
    Symbol,
)
from signaldesk_cli.main import _format_provider_health, _run_provider_health_checks, app
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


def test_health_command() -> None:
    result = CliRunner().invoke(app, ["health"])

    assert result.exit_code == 0
    assert "SignalDesk is configured for local." in result.stdout


def test_providers_check_is_available_from_help() -> None:
    result = CliRunner().invoke(app, ["providers", "--help"])

    assert result.exit_code == 0
    assert "check" in result.stdout


def test_providers_check_reports_default_local_provider_without_secrets() -> None:
    result = CliRunner().invoke(app, ["providers", "check"])

    assert result.exit_code == 0
    assert "provider\tstatus\tresult" in result.stdout
    assert "local-fixture\tok\tready (no external credentials required)" in result.stdout
    assert "API_KEY" not in result.stdout
    assert "TOKEN" not in result.stdout


def test_provider_health_formatter_reports_failure_status() -> None:
    line = _format_provider_health(
        "broken",
        ProviderResult.failure(provider="broken", error="unavailable without configured adapter"),
    )

    assert line == "broken\tfailed\tunavailable without configured adapter"


def test_provider_health_checks_convert_exceptions_to_sanitized_failures() -> None:
    exit_code, lines = _run_provider_health_checks(ProviderRegistry((ExplodingProvider(),)))

    assert exit_code == 1
    assert lines == (
        "provider\tstatus\tresult",
        "exploding\tfailed\thealth check raised an exception",
    )
    assert "secret detail" not in "\n".join(lines)
