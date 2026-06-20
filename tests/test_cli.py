from signaldesk_backend import ProviderResult
from signaldesk_cli.main import _format_provider_health, app
from typer.testing import CliRunner


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
