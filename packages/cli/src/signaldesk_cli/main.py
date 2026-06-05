import typer
from signaldesk_backend import Settings

app = typer.Typer(help="SignalDesk command-line interface.")


@app.callback()
def main() -> None:
    """SignalDesk command-line interface."""


@app.command()
def health() -> None:
    """Print a basic local configuration health check."""
    settings = Settings.from_env()
    typer.echo(f"SignalDesk is configured for {settings.app_env}.")


if __name__ == "__main__":
    app()
