from signaldesk_cli.main import app
from typer.testing import CliRunner


def test_health_command() -> None:
    result = CliRunner().invoke(app, ["health"])

    assert result.exit_code == 0
    assert "SignalDesk is configured for local." in result.stdout
