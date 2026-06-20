import typer
from signaldesk_backend import ProviderRegistry, ProviderResult, Settings, default_provider_registry

app = typer.Typer(help="SignalDesk command-line interface.")
providers_app = typer.Typer(help="Inspect configured market-data providers.")
app.add_typer(providers_app, name="providers")


@app.callback()
def main() -> None:
    """SignalDesk command-line interface."""


@app.command()
def health() -> None:
    """Print a basic local configuration health check."""
    settings = Settings.from_env()
    typer.echo(f"SignalDesk is configured for {settings.app_env}.")


def _format_provider_health(provider_name: str, result: ProviderResult[str]) -> str:
    status = "ok" if result.ok else "failed"
    detail = result.data if result.ok else result.error
    return f"{provider_name}\t{status}\t{detail}"


def _run_provider_health_checks(registry: ProviderRegistry) -> tuple[int, tuple[str, ...]]:
    lines = ["provider\tstatus\tresult"]
    exit_code = 0
    for provider in registry.list():
        try:
            result = provider.health_check()
        except Exception:
            result = ProviderResult.failure(
                provider=provider.name,
                error="health check raised an exception",
            )
        lines.append(_format_provider_health(provider.name, result))
        if not result.ok:
            exit_code = 1
    return exit_code, tuple(lines)


@providers_app.command("check")
def providers_check() -> None:
    """Run safe local health checks for registered market-data providers."""

    exit_code, lines = _run_provider_health_checks(default_provider_registry())
    for line in lines:
        typer.echo(line)
    if exit_code:
        raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()
