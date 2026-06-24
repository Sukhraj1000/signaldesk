import csv
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import typer
from signaldesk_backend import (
    Candle,
    ConfirmationInvalidationLevel,
    FibonacciRetracementLevel,
    ProviderRegistry,
    ProviderResult,
    ProviderRoleConfig,
    RiskFlag,
    ScoreBreakdown,
    Settings,
    Symbol,
    assemble_ta_signal_card_report,
    assess_technical_analysis_risks,
    average_true_range,
    build_openai_compatible_chat_messages,
    build_ta_llm_prompt_payload,
    calculate_fibonacci_retracement_levels,
    classify_trend_regime,
    classify_volatility_regime,
    classify_volume_regime,
    default_provider_registry,
    derive_confirmation_invalidation_levels,
    detect_breakout_breakdown_events,
    detect_moving_average_cross_events,
    detect_overextension_events,
    detect_relative_volume_spike_events,
    detect_swing_highs,
    detect_swing_lows,
    detect_trend_regime_shift_events,
    detect_volatility_regime_events,
    exponential_moving_average,
    extract_ta_signal_card,
    llm_explanation_output_schema,
    macd,
    parse_llm_explanation_response_content,
    redact_provider_diagnostic,
    relative_strength_index,
    relative_volume,
    resolve_provider_mode,
    score_technical_analysis,
    simple_moving_average,
    validate_ta_signal_card_report,
    volume_moving_average,
)

app = typer.Typer(help="SignalDesk command-line interface.")

ENHANCED_CONTEXT_STALE_AFTER = timedelta(days=7)
providers_app = typer.Typer(help="Inspect configured market-data providers.")
config_app = typer.Typer(help="Inspect local SignalDesk configuration without exposing secrets.")
fixtures_app = typer.Typer(help="Generate deterministic local fixture data.")
llm_app = typer.Typer(
    help="Inspect guarded optional LLM explanation payloads without calling an LLM."
)
app.add_typer(providers_app, name="providers")
app.add_typer(config_app, name="config")
app.add_typer(fixtures_app, name="fixtures")
app.add_typer(llm_app, name="llm")


@app.callback()
def main() -> None:
    """SignalDesk command-line interface."""


@app.command()
def health() -> None:
    """Print a basic local configuration health check."""
    settings = Settings.from_env()
    typer.echo(f"SignalDesk is configured for {settings.app_env}.")


def _parse_fixture_as_of(value: str) -> datetime:
    try:
        parsed = datetime.strptime(value.strip(), "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("--as-of must use YYYY-MM-DD format") from exc
    return parsed.replace(tzinfo=UTC)


def _fixture_output_path(output_dir: Path, symbol: str) -> Path:
    safe_symbol = Symbol(symbol).ticker.lower().replace("/", "-")
    return output_dir / f"{safe_symbol}-1d.csv"


def _fixture_candle_rows(symbol: str, *, days: int, as_of: datetime) -> list[dict[str, str]]:
    requested_symbol = Symbol(symbol)
    provider = default_provider_registry().get("local-fixture")
    result = provider.get_historical_candles(
        requested_symbol,
        start=as_of - timedelta(days=days - 1),
        end=as_of,
        interval="1d",
    )
    if not result.ok or not result.data:
        diagnostic = redact_provider_diagnostic(result.error or "local fixture returned no candles")
        raise RuntimeError(f"local-fixture failed for {requested_symbol.ticker}: {diagnostic}")
    return [
        {
            "Date": candle.timestamp.date().isoformat(),
            "Open": str(candle.open),
            "High": str(candle.high),
            "Low": str(candle.low),
            "Close": str(candle.close),
            "Volume": str(candle.volume),
        }
        for candle in result.data
    ]


def _write_fixture_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=("Date", "Open", "High", "Low", "Close", "Volume")
        )
        writer.writeheader()
        writer.writerows(rows)


@fixtures_app.command("generate")
def fixtures_generate(
    symbols: list[str] | None = typer.Option(  # noqa: B008
        None,
        "--symbol",
        "-s",
        help="Symbol to generate. Repeat for multiple symbols. Defaults to AMD and MSFT.",
    ),
    output_dir: Path = typer.Option(  # noqa: B008
        Path("fixtures/local"),
        "--output-dir",
        help="Directory for generated local CSV fixture files.",
    ),
    days: int = typer.Option(60, min=1, max=60, help="Number of daily candles to write."),
    as_of: str = typer.Option("2024-12-31", help="Final fixture candle date in YYYY-MM-DD format."),
    output: str = typer.Option("table", help="Output format: table or json."),
) -> None:
    """Generate deterministic CSV fixtures compatible with the local-csv provider."""

    output_format = output.strip().lower()
    if output_format not in {"table", "json"}:
        typer.echo("--output must be 'table' or 'json'.", err=True)
        raise typer.Exit(2)
    try:
        fixture_as_of = _parse_fixture_as_of(as_of)
        requested_symbols = tuple(
            dict.fromkeys(Symbol(symbol).ticker for symbol in (symbols or ["AMD", "MSFT"]))
        )
        if not requested_symbols:
            raise ValueError("at least one --symbol is required")
        generated_files = []
        for symbol in requested_symbols:
            rows = _fixture_candle_rows(symbol, days=days, as_of=fixture_as_of)
            path = _fixture_output_path(output_dir, symbol)
            _write_fixture_csv(path, rows)
            generated_files.append(
                {
                    "symbol": symbol,
                    "path": str(path),
                    "rows": len(rows),
                    "provider": "local-fixture",
                    "compatible_provider": "local-csv",
                    "interval": "1d",
                    "as_of": fixture_as_of.date().isoformat(),
                }
            )
    except (RuntimeError, OSError, ValueError) as exc:
        typer.echo(redact_provider_diagnostic(str(exc)), err=True)
        raise typer.Exit(1 if isinstance(exc, (RuntimeError, OSError)) else 2) from exc

    payload = {
        "schema_version": "signaldesk.fixtures.v1",
        "generated": generated_files,
    }
    if output_format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return
    typer.echo("symbol\tpath\trows\tprovider\tcompatible_provider\tinterval\tas_of")
    for item in generated_files:
        typer.echo(
            f"{item['symbol']}\t{item['path']}\t{item['rows']}\t{item['provider']}\t"
            f"{item['compatible_provider']}\t{item['interval']}\t{item['as_of']}"
        )


def _redact_url_secret(value: str) -> str:
    """Redact URL userinfo secrets while preserving operational context."""

    try:
        parts = urlsplit(value)
    except ValueError:
        return redact_provider_diagnostic(value)
    if not parts.scheme or not parts.netloc:
        return redact_provider_diagnostic(value)
    host = parts.hostname or ""
    if not host:
        return redact_provider_diagnostic(value)
    netloc = host
    if parts.port is not None:
        netloc = f"{netloc}:{parts.port}"
    if parts.username is not None:
        username = parts.username
        netloc = f"{username}:<redacted>@{netloc}"
    return redact_provider_diagnostic(
        urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    )


def _config_inspect_payload(settings: Settings) -> dict[str, str]:
    """Return configuration fields safe for terminal or JSON output."""

    return {
        "app_env": settings.app_env,
        "log_level": settings.log_level,
        "database_url": _redact_url_secret(settings.database_url),
        "redis_url": _redact_url_secret(settings.redis_url),
        "llm_provider": settings.llm_provider,
    }


def _format_config_inspect(payload: dict[str, str]) -> tuple[str, ...]:
    lines = ["setting\tvalue"]
    lines.extend(f"{key}\t{value}" for key, value in payload.items())
    return tuple(lines)


@config_app.command("inspect")
def config_inspect(
    output: str = typer.Option("table", help="Output format: table or json."),
) -> None:
    """Print sanitized local configuration values without checking external services."""

    output_format = output.strip().lower()
    if output_format not in {"table", "json"}:
        typer.echo("--output must be 'table' or 'json'.", err=True)
        raise typer.Exit(2)

    payload = _config_inspect_payload(Settings.from_env())
    if output_format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    for line in _format_config_inspect(payload):
        typer.echo(line)


@app.command("ta")
def technical_analysis(
    symbol: str,
    provider: str | None = typer.Option(
        None,
        help=(
            "Registered market-data provider to use. When omitted, SignalDesk "
            "uses --mode role resolution."
        ),
    ),
    mode: str = typer.Option(
        "default",
        help="Provider role mode to resolve when --provider is omitted: default or enhanced.",
    ),
    llm: str = typer.Option("none", help="LLM provider. Only 'none' is currently supported."),
    interval: str = typer.Option("1d", help="Historical candle interval."),
    days: int = typer.Option(120, min=1, help="Number of calendar days of history to request."),
    output: str = typer.Option("table", help="Output format: table, json, or markdown."),
) -> None:
    """Fetch candles and run deterministic technical analysis for one symbol."""

    if llm.strip().lower() != "none":
        typer.echo("Only --llm none is currently supported.", err=True)
        raise typer.Exit(2)

    output_format = output.strip().lower()
    if output_format not in {"table", "json", "markdown", "md"}:
        typer.echo("--output must be 'table', 'json', 'markdown', or 'md'.", err=True)
        raise typer.Exit(2)

    registry = default_provider_registry()
    try:
        report = _fetch_ta_report(
            registry,
            symbol=symbol,
            provider=provider,
            mode=mode,
            interval=interval,
            days=days,
            as_of=datetime.now(UTC),
        )
    except (KeyError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    validate_ta_signal_card_report(report)
    if output_format == "json":
        typer.echo(json.dumps(report, indent=2, sort_keys=True))
        return
    if output_format in {"markdown", "md"}:
        typer.echo(_format_ta_markdown(report), nl=False)
        return

    for key, value in _ta_table_report_values(report).items():
        typer.echo(f"{key}\t{value}")


def _format_ta_markdown(report: dict[str, Any]) -> str:
    """Render a compact Markdown report from the canonical TA signal card."""

    card = extract_ta_signal_card(report)
    identity = card["identity"]
    facts = card["facts"]
    trend = card["trend"]
    levels = card["levels"]
    risk = card["risk"]
    score = card["score"]
    provider_mode = card["provider_mode"]
    unavailable_context = card["unavailable_context"]

    setup_scores = [item for item in score["breakdowns"] if item["category"] == "setup_quality"]
    risk_scores = [item for item in score["breakdowns"] if item["category"] == "risk"]
    trend_regime = trend["regimes"]["trend"]
    generated_at = identity["generated_at"]
    setup_quality_score = setup_scores[0]["score"] if setup_scores else "unavailable"
    risk_score = risk_scores[0]["score"] if risk_scores else "unavailable"
    confirmation_level = _format_optional_level(levels["confirmation"])
    invalidation_level = _format_optional_level(levels["invalidation"])

    lines = [
        f"# SignalDesk TA report: {identity['symbol']}",
        "",
        "## Facts",
        f"- Generated at: `{generated_at}`",
        f"- Schema version: `{identity['schema_version']}`",
        f"- Symbol: `{identity['symbol']}`",
        f"- Timeframe: `{identity['timeframe']}`",
        f"- Provider mode: `{provider_mode['mode']}`",
        f"- Price provider: `{provider_mode['price_provider']}`",
        f"- Candles: `{facts['candles']}`",
        f"- Latest close: `{facts['latest_close']}` at `{facts['latest_timestamp']}`",
        *_format_enhanced_fact_lines(facts),
        *_markdown_report_boundary_lines(),
        "",
        "## Setup",
        f"- What is the setup? `{trend_regime['regime']}` trend regime with setup quality "
        f"`{setup_quality_score}` and risk `{risk_score}`.",
        f"- Why it matters: {trend_regime['reason']}",
        "",
        "## Deterministic signals",
        f"- Trend regime: `{trend_regime['regime']}` — {trend_regime['reason']}",
        f"- Confirmation level: `{confirmation_level}`",
        f"- Invalidation level: `{invalidation_level}`",
        f"- Setup quality score: `{setup_quality_score}`",
        f"- Risk score: `{risk_score}`",
    ]
    lines.extend(_format_score_reason_lines(score["breakdowns"]))
    lines.extend(
        [
            "",
            "## Technical events",
            *_format_technical_event_lines(card["events"]),
            "",
            "## Confirmation and invalidation",
        ]
    )
    lines.extend(
        [
            f"- What confirms it: `{confirmation_level}`",
            f"- What invalidates it: `{invalidation_level}`",
            "",
            "## Risks",
        ]
    )
    for flag in risk["flags"]:
        lines.append(
            f"- `{flag['severity']}` `{flag['kind']}`: {flag['message']} "
            f"(source: `{flag['source']}`)"
        )
    lines.extend(["", "## Unavailable context"])
    if unavailable_context:
        for item in unavailable_context:
            lines.append(f"- {_unavailable_context_text(item)}")
    else:
        lines.append("- none")
    lines.extend(["", "## Provenance"])
    for provenance in card["provenance"]:
        lines.append(
            _format_provenance_markdown_line(
                provenance, fallback_generated_at=identity["generated_at"]
            )
        )
    narrative = card.get("narrative") or "unavailable"
    lines.extend(
        ["", "## Optional narrative", f"- LLM: `{card['llm']}`", f"- Narrative: {narrative}"]
    )
    return "\n".join(lines) + "\n"


def _format_optional_level(level: dict[str, Any] | None) -> str:
    if level is None:
        return "unavailable"
    return "{} ({})".format(level["price"], level["source_rule"])


def _markdown_report_boundary_lines() -> list[str]:
    """Return user-facing boundaries shared by Markdown report renderers."""

    return [
        "",
        "## Report boundaries",
        (
            "- Facts, deterministic signals, risks, unavailable context, and optional "
            "narrative are rendered separately."
        ),
        (
            "- Missing enhanced provider or LLM context is unavailable context, not a "
            "silent all-clear."
        ),
        (
            "- This report is not investment advice and does not include trade "
            "execution instructions."
        ),
    ]


def _format_provenance_markdown_line(
    provenance: dict[str, Any],
    *,
    fallback_generated_at: str = "unavailable",
    prefix: str = "",
) -> str:
    """Return compact provenance with inputs for Markdown signal cards."""

    inputs = ", ".join(provenance.get("inputs", [])) or "none"
    generated_at = provenance.get("generated_at") or fallback_generated_at
    return (
        f"- {prefix}provider `{provenance['provider']}`, source `{provenance['source']}`, "
        f"timeframe `{provenance['timeframe']}`, inputs `{inputs}`, "
        f"generated at `{generated_at}`, observations `{provenance['observations']}`"
    )


def _markdown_inline_code_text(value: object) -> str:
    """Return provider text safe for Markdown inline-code output."""

    flat_text = _flat_table_cell_text(value)
    control_safe_text = "".join(
        character if ord(character) >= 32 and ord(character) != 127 else " "
        for character in flat_text
    )
    return control_safe_text.replace("`", r"\`")


def _format_enhanced_fact_lines(facts: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    fundamentals = facts.get("fundamentals")
    if isinstance(fundamentals, dict):
        company_name = _markdown_inline_code_text(
            fundamentals.get("company_name") or fundamentals.get("symbol") or "unknown"
        )
        provider = _markdown_inline_code_text(fundamentals.get("provider") or "unknown")
        sector = _markdown_inline_code_text(fundamentals.get("sector") or "sector unavailable")
        industry = _markdown_inline_code_text(
            fundamentals.get("industry") or "industry unavailable"
        )
        lines.append(
            f"- Fundamentals: `{company_name}` via `{provider}`; "
            f"sector `{sector}`, industry `{industry}`"
        )
    catalysts = facts.get("catalysts")
    if isinstance(catalysts, dict):
        events = catalysts.get("events")
        event_items = events if isinstance(events, list) else []
        event_count = len(event_items)
        provider = _markdown_inline_code_text(catalysts.get("provider") or "unknown")
        if event_count:
            first_event = event_items[0]
            headline_value = (
                first_event.get("headline", "headline unavailable")
                if isinstance(first_event, dict)
                else "headline unavailable"
            )
            headline = _markdown_inline_code_text(headline_value)
            lines.append(
                f"- Catalysts: `{event_count}` event(s) via `{provider}`; latest `{headline}`"
            )
        else:
            lines.append(f"- Catalysts: `0` event(s) via `{provider}`")
    return lines


def _summarize_enhanced_context(facts: dict[str, Any]) -> str:
    summaries: list[str] = []
    fundamentals = facts.get("fundamentals")
    if isinstance(fundamentals, dict):
        company_name = _flat_table_cell_text(
            fundamentals.get("company_name") or fundamentals.get("symbol") or "unknown"
        )
        provider = _flat_table_cell_text(fundamentals.get("provider") or "unknown")
        sector = _flat_table_cell_text(fundamentals.get("sector") or "sector unavailable")
        industry = _flat_table_cell_text(fundamentals.get("industry") or "industry unavailable")
        summaries.append(f"fundamentals via {provider}: {company_name} ({sector}/{industry})")
    catalysts = facts.get("catalysts")
    if isinstance(catalysts, dict):
        events = catalysts.get("events")
        event_items = events if isinstance(events, list) else []
        event_count = len(event_items)
        provider = _flat_table_cell_text(catalysts.get("provider") or "unknown")
        if event_count:
            first_event = event_items[0]
            headline_value = (
                first_event.get("headline", "headline unavailable")
                if isinstance(first_event, dict)
                else "headline unavailable"
            )
            headline = _flat_table_cell_text(headline_value)
            summaries.append(f"catalysts via {provider}: {event_count} event(s), latest {headline}")
        else:
            summaries.append(f"catalysts via {provider}: 0 event(s)")
    return "; ".join(summaries) if summaries else "none"


def _format_score_reason_lines(score_breakdowns: list[dict[str, Any]]) -> list[str]:
    """Return compact deterministic score reasons for Markdown reports."""

    if not score_breakdowns:
        return ["- Score reasons: unavailable"]
    lines = ["- Score reasons:"]
    for breakdown in score_breakdowns:
        reasons = breakdown.get("reasons", [])
        if not reasons:
            lines.append(
                "  - `{}` `{}`: no deterministic reason details available.".format(
                    breakdown.get("category", "unknown"),
                    breakdown.get("score", "unavailable"),
                )
            )
            continue
        reason_text = "; ".join(
            "{} ({})".format(
                reason.get("message", "no message provided"),
                reason.get("source", "unknown_source"),
            )
            for reason in reasons[:3]
        )
        omitted_count = len(reasons) - 3
        omitted_suffix = f"; {omitted_count} more reason(s) omitted" if omitted_count > 0 else ""
        lines.append(
            "  - `{}` `{}`: {}{}".format(
                breakdown.get("category", "unknown"),
                breakdown.get("score", "unavailable"),
                reason_text,
                omitted_suffix,
            )
        )
    return lines


def _format_technical_event_lines(events: tuple[dict[str, Any], ...]) -> list[str]:
    """Return compact event lines without dumping raw indicator payloads."""

    if not events:
        return ["- none detected"]
    lines = []
    for event in events[:5]:
        lines.append(
            "- `{}` `{}` at `{}`: {} (source: `{}`)".format(
                event.get("severity", "unknown"),
                event.get("event_type", "unknown_event"),
                event.get("timestamp", "unknown_time"),
                event.get("reason", "no reason provided"),
                event.get("source_rule", "unknown_source"),
            )
        )
    omitted_count = len(events) - 5
    if omitted_count > 0:
        lines.append(f"- {omitted_count} more event(s) omitted for compactness")
    return lines


def _unavailable_context_text(item: dict[str, Any]) -> str:
    provider_name = item.get("provider") or "none"
    details = item.get("details")
    suffix = f" Details: {details}" if details else ""
    return "`{}` via `{}`: {}.{}".format(
        item.get("context_type", "unknown"),
        provider_name,
        item.get("reason", "unavailable"),
        suffix,
    )


def _summarize_unavailable_context(items: list[dict[str, Any]]) -> str:
    if not items:
        return "none"
    return "; ".join(
        "{} via {}: {}{}".format(
            item.get("context_type", "unknown"),
            item.get("provider") or "none",
            item.get("reason", "unavailable"),
            f" Details: {item['details']}" if item.get("details") else "",
        )
        for item in items
    )


def _summarize_risk_flags(flags: list[dict[str, Any]]) -> str:
    if not flags:
        return "none"
    return "; ".join(
        "{} {}: {}".format(
            flag.get("severity", "unknown"),
            flag.get("kind", "unknown"),
            flag.get("message", "no message provided"),
        )
        for flag in flags
    )


def _format_optional_table_level(level: dict[str, Any] | None) -> str:
    if level is None:
        return "unavailable"
    source_rule = level.get("source_rule") or level.get("source") or "unknown_source"
    return "{} ({})".format(
        _flat_table_cell_text(level.get("price", "unavailable")),
        _flat_table_cell_text(source_rule),
    )


def _summarize_regime(regime: dict[str, Any]) -> str:
    return "{}: {}".format(
        _flat_table_cell_text(regime.get("regime", "unknown")),
        _flat_table_cell_text(regime.get("reason", "no reason provided")),
    )


def _summarize_technical_events(events: tuple[dict[str, Any], ...]) -> str:
    if not events:
        return "none detected"
    summaries = []
    for event in events[:3]:
        summaries.append(
            "{} {} at {}: {}".format(
                _flat_table_cell_text(event.get("severity", "unknown")),
                _flat_table_cell_text(event.get("event_type", "unknown_event")),
                _flat_table_cell_text(event.get("timestamp", "unknown_time")),
                _flat_table_cell_text(event.get("reason", "no reason provided")),
            )
        )
    omitted_count = len(events) - 3
    if omitted_count > 0:
        summaries.append(f"{omitted_count} more event(s) omitted")
    return "; ".join(summaries)


def _fetch_ta_report(
    registry: ProviderRegistry,
    *,
    symbol: str,
    provider: str | None,
    mode: str,
    interval: str,
    days: int,
    as_of: datetime,
) -> dict[str, Any]:
    requested_symbol = Symbol(symbol)
    (
        market_data_provider,
        provider_mode_payload,
        mode_unavailable_context,
    ) = _resolve_ta_provider(registry, provider=provider, mode=mode)

    start = as_of - timedelta(days=days)
    result = market_data_provider.get_historical_candles(
        requested_symbol, start=start, end=as_of, interval=interval
    )
    if not result.ok or not result.data:
        diagnostic = redact_provider_diagnostic(result.error or "provider returned no candles")
        raise RuntimeError(
            f"{market_data_provider.name} failed for {requested_symbol.ticker}: {diagnostic}"
        )

    context_payloads = _enhanced_context_payloads(
        registry=registry,
        symbol=requested_symbol,
        provider_mode=provider_mode_payload,
        as_of=as_of,
    )
    report = _technical_analysis_report(
        symbol=requested_symbol,
        provider_name=market_data_provider.name,
        candles=result.data,
        interval=interval,
        provider_mode=provider_mode_payload,
        as_of=as_of,
        mode_unavailable_context=mode_unavailable_context,
        enhanced_facts=context_payloads["facts"],
        enhanced_provenance=context_payloads["provenance"],
        enhanced_unavailable_context=context_payloads["unavailable_context"],
    )
    validate_ta_signal_card_report(report)
    return report


def _yaml_scalar(value: str) -> str | bool | None:
    normalized = value.strip().strip("'\"")
    if normalized.lower() in {"true", "yes", "on"}:
        return True
    if normalized.lower() in {"false", "no", "off"}:
        return False
    if normalized.lower() in {"null", "none", "~", ""}:
        return None
    return normalized


def _load_watchlist_model(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"watchlist file not found: {path}")
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"watchlist file could not be read: {path}") from exc

    metadata: dict[str, Any] = {
        "name": path.stem,
        "tags": [],
        "asset_class": "equity",
        "provider_preference": None,
        "enabled": True,
        "notes": None,
    }
    symbols: list[str] = []
    current_list: str | None = None
    for raw_line in raw_lines:
        line_without_comment = raw_line.split("#", 1)[0].rstrip()
        stripped = line_without_comment.strip()
        if not stripped:
            continue
        if stripped.startswith("-"):
            item = stripped[1:].strip().strip("'\"")
            if current_list == "symbols" and item:
                symbols.append(Symbol(item).ticker)
            elif current_list == "tags" and item:
                metadata["tags"].append(item)
            continue
        current_list = None
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        normalized_key = key.strip().replace("-", "_")
        if normalized_key in {"symbols", "tags"} and not value.strip():
            current_list = normalized_key
            continue
        if normalized_key in metadata:
            metadata[normalized_key] = _yaml_scalar(value)

    if not symbols:
        raise ValueError(f"watchlist file has no symbols: {path}")
    if not isinstance(metadata["enabled"], bool):
        raise ValueError(f"watchlist enabled must be true or false: {path}")

    metadata["symbols"] = list(dict.fromkeys(symbols))
    metadata["tags"] = list(dict.fromkeys(str(tag) for tag in metadata["tags"] if str(tag)))
    metadata["asset_class"] = str(metadata["asset_class"] or "equity").strip().lower()
    metadata["name"] = str(metadata["name"] or path.stem).strip()
    metadata["provider_preference"] = (
        str(metadata["provider_preference"]).strip()
        if metadata["provider_preference"] is not None
        else None
    )
    metadata["notes"] = str(metadata["notes"]).strip() if metadata["notes"] else None
    return metadata


def _load_watchlist_symbols(path: Path) -> tuple[str, ...]:
    return tuple(_load_watchlist_model(path)["symbols"])


def _scan_result_summary(report: dict[str, Any]) -> dict[str, Any]:
    card = extract_ta_signal_card(report)
    setup_scores = [
        score for score in card["score"]["breakdowns"] if score["category"] == "setup_quality"
    ]
    risk_scores = [score for score in card["score"]["breakdowns"] if score["category"] == "risk"]
    return {
        "schema_version": card["identity"]["schema_version"],
        "signal_card": card,
        "generated_at": card["identity"]["generated_at"],
        "symbol": card["identity"]["symbol"],
        "provider": card["facts"]["provider"],
        "interval": card["facts"]["interval"],
        "candles": card["facts"]["candles"],
        "latest_timestamp": card["facts"]["latest_timestamp"],
        "latest_close": card["facts"]["latest_close"],
        "trend_regime": card["trend"]["regimes"]["trend"],
        "confirmation_level": card["levels"]["confirmation"],
        "invalidation_level": card["levels"]["invalidation"],
        "risk_flags": card["risk"]["flags"],
        "score_breakdowns": card["score"]["breakdowns"],
        "technical_events": card["events"],
        "unavailable_context": card["unavailable_context"],
        "enhanced_context_summary": _summarize_enhanced_context(card["facts"]),
        "llm": card["llm"],
        "narrative": card["narrative"],
        "setup_quality_score": setup_scores[0]["score"] if setup_scores else None,
        "risk_score": risk_scores[0]["score"] if risk_scores else None,
        "provenance": card["provenance"],
    }


def _format_scan_table(payload: dict[str, Any]) -> tuple[str, ...]:
    header = (
        "rank	symbol	status	provider	latest_close	trend_regime	"
        "setup_quality_score	risk_score	unavailable_context"
    )
    lines = [header]
    for result in payload["ranked_setups"]:
        summary = result["summary"]
        lines.append(
            f"{result['rank']}	"
            f"{summary['symbol']}	ok	"
            f"{summary['provider']}	"
            f"{summary['latest_close']}	"
            f"{summary['trend_regime']['regime']}	"
            f"{summary['setup_quality_score']}	"
            f"{summary['risk_score']}	"
            f"{len(summary['unavailable_context'])}"
        )
    for result in payload["failed_symbols"]:
        lines.append(f"	{result['symbol']}	failed						{result['error']}")
    for result in payload["skipped_symbols"]:
        lines.append(f"\t{result['symbol']}\tskipped\t\t\t\t\t\t{result['reason']}")
    summary = payload["summary"]
    lines.append(
        "summary\t\t\t\t\t"
        + "ok={ok} failed={failed} skipped={skipped} total={total}".format(**summary)
    )
    return tuple(lines)


@llm_app.command("output-schema")
def llm_output_schema(
    output: str = typer.Option("json", help="Output format: json."),
) -> None:
    """Render the fail-closed LLM explanation output JSON schema."""

    if output.strip().lower() != "json":
        typer.echo("--output must be 'json'.", err=True)
        raise typer.Exit(2)
    typer.echo(json.dumps(llm_explanation_output_schema(), indent=2, sort_keys=True))


@llm_app.command("prompt-payload")
def llm_prompt_payload(
    symbol: str,
    provider: str | None = typer.Option(
        None,
        help=(
            "Registered market-data provider to use. When omitted, SignalDesk "
            "uses --mode role resolution."
        ),
    ),
    mode: str = typer.Option("default", help="Provider role mode: default or enhanced."),
    interval: str = typer.Option("1d", help="Historical candle interval."),
    days: int = typer.Option(120, min=1, help="Number of calendar days of history to request."),
    output: str = typer.Option("json", help="Output format: json."),
) -> None:
    if output.strip().lower() != "json":
        typer.echo("--output must be 'json'.", err=True)
        raise typer.Exit(2)

    registry = default_provider_registry()
    try:
        report = _fetch_ta_report(
            registry,
            symbol=symbol,
            provider=provider,
            mode=mode,
            interval=interval,
            days=days,
            as_of=datetime.now(UTC),
        )
        payload = build_ta_llm_prompt_payload(report)
    except (KeyError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc

    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


@llm_app.command("chat-messages")
def llm_chat_messages(
    symbol: str,
    provider: str | None = typer.Option(
        None,
        help=(
            "Registered market-data provider to use. When omitted, SignalDesk "
            "uses --mode role resolution."
        ),
    ),
    mode: str = typer.Option("default", help="Provider role mode: default or enhanced."),
    interval: str = typer.Option("1d", help="Historical candle interval."),
    days: int = typer.Option(120, min=1, help="Number of calendar days of history to request."),
    output: str = typer.Option("json", help="Output format: json."),
) -> None:
    """Render guarded OpenAI-compatible chat messages without calling an LLM."""
    if output.strip().lower() != "json":
        typer.echo("--output must be 'json'.", err=True)
        raise typer.Exit(2)
    registry = default_provider_registry()
    try:
        report = _fetch_ta_report(
            registry,
            symbol=symbol,
            provider=provider,
            mode=mode,
            interval=interval,
            days=days,
            as_of=datetime.now(UTC),
        )
        payload = build_ta_llm_prompt_payload(report)
        messages = build_openai_compatible_chat_messages(payload)
    except (KeyError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    except RuntimeError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(messages, indent=2, sort_keys=True))


@llm_app.command("validate-output")
def llm_validate_output(
    path: Path = typer.Argument(  # noqa: B008
        ..., help="Path to a candidate LLM explanation JSON object."
    ),
) -> None:
    """Validate optional LLM explanation output without calling an LLM."""

    try:
        validated = parse_llm_explanation_response_content(path.read_text(encoding="utf-8"))
    except OSError as exc:
        typer.echo(redact_provider_diagnostic(f"could not read LLM output JSON: {exc}"), err=True)
        raise typer.Exit(1) from exc
    except ValueError as exc:
        typer.echo("invalid LLM explanation output: schema validation failed", err=True)
        raise typer.Exit(1) from exc

    typer.echo(json.dumps(validated, indent=2, sort_keys=True))


@app.command("scan")
def scan_watchlist(
    watchlist: Path = typer.Option(  # noqa: B008
        ..., help="YAML watchlist containing a top-level symbols list."
    ),
    provider: str | None = typer.Option(
        None,
        help=(
            "Registered price provider to use for every symbol. When omitted, SignalDesk "
            "uses --mode role resolution."
        ),
    ),
    mode: str = typer.Option("default", help="Provider role mode: default or enhanced."),
    llm: str = typer.Option("none", help="LLM provider. Only 'none' is currently supported."),
    interval: str = typer.Option("1d", help="Historical candle interval."),
    days: int = typer.Option(120, min=1, help="Number of calendar days of history to request."),
    output: str = typer.Option("table", help="Output format: table, json, or markdown."),
    max_workers: int = typer.Option(
        4,
        min=1,
        max=16,
        help="Maximum concurrent symbol fetches for the watchlist scan.",
    ),
) -> None:
    """Run deterministic TA summaries for every symbol in a watchlist."""

    if llm.strip().lower() != "none":
        typer.echo("Only --llm none is currently supported.", err=True)
        raise typer.Exit(2)
    output_format = output.strip().lower()
    if output_format not in {"table", "json", "markdown", "md"}:
        typer.echo("--output must be 'table', 'json', 'markdown', or 'md'.", err=True)
        raise typer.Exit(2)

    try:
        watchlist_model = _load_watchlist_model(watchlist)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    try:
        exit_code, payload = _scan_watchlist_payload(
            watchlist_model=watchlist_model,
            watchlist=watchlist,
            provider=provider,
            mode=mode,
            interval=interval,
            days=days,
            max_workers=max_workers,
        )
    except (KeyError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    if output_format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    elif output_format in {"markdown", "md"}:
        typer.echo(_format_report_markdown(payload), nl=False)
    else:
        for line in _format_scan_table(payload):
            typer.echo(line)
    if exit_code:
        raise typer.Exit(exit_code)


def _explicit_provider_mode_payload(registry: ProviderRegistry, provider: str) -> dict[str, Any]:
    provider_name = registry.get(provider.strip()).name
    return {
        "mode": "explicit",
        "price_provider": provider_name,
        "fundamentals_provider": None,
        "catalyst_provider": None,
        "llm_provider": None,
        "unavailable_context": [],
    }


def _watchlist_price_provider_preference(
    watchlist_model: dict[str, Any], provider: str | None
) -> str | None:
    explicit_provider = provider.strip() if provider is not None else ""
    if explicit_provider:
        return explicit_provider
    preference = watchlist_model.get("provider_preference")
    if preference is None:
        return None
    normalized_preference = str(preference).strip()
    return normalized_preference or None


def _watchlist_scan_summary(
    results: list[dict[str, Any]],
    ranked_setups: list[dict[str, Any]],
    failed_symbols: list[dict[str, Any]],
    skipped_symbols: list[dict[str, Any]],
) -> dict[str, int]:
    return {
        "total": len(results),
        "ok": len(ranked_setups),
        "failed": len(failed_symbols),
        "skipped": len(skipped_symbols),
    }


WATCHLIST_REPORT_SCHEMA_VERSION = "signaldesk.watchlist_report.v1"


def _watchlist_report_provenance(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return compact report-level provenance for successful signal cards."""

    provenance_items: list[dict[str, Any]] = []
    for result in results:
        if result["status"] != "ok":
            continue
        summary = result["summary"]
        for provenance in summary["provenance"]:
            provenance_items.append(
                {
                    "symbol": summary["symbol"],
                    "provider": provenance["provider"],
                    "source": provenance["source"],
                    "timeframe": provenance["timeframe"],
                    "inputs": provenance.get("inputs", []),
                    "generated_at": provenance.get("generated_at") or summary["generated_at"],
                    "observations": provenance["observations"],
                }
            )
    return provenance_items


def _watchlist_report_payload(
    *,
    watchlist: Path,
    watchlist_model: dict[str, Any],
    scanned_at: datetime,
    provider_mode: dict[str, Any],
    symbols: tuple[str, ...],
    results: list[dict[str, Any]],
    ranked_setups: list[dict[str, Any]],
    failed_symbols: list[dict[str, Any]],
    skipped_symbols: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return the stable JSON/Markdown payload for watchlist reports."""

    return {
        "schema_version": WATCHLIST_REPORT_SCHEMA_VERSION,
        "report_type": "watchlist",
        "generated_at": scanned_at.isoformat(),
        "watchlist": str(watchlist),
        "watchlist_model": watchlist_model,
        "scanned_at": scanned_at.isoformat(),
        "provider_mode": provider_mode,
        "symbols": list(symbols),
        "results": results,
        "ranked_setups": ranked_setups,
        "failed_symbols": failed_symbols,
        "skipped_symbols": skipped_symbols,
        "summary": _watchlist_scan_summary(results, ranked_setups, failed_symbols, skipped_symbols),
        "provenance": _watchlist_report_provenance(results),
    }


def _scan_watchlist_payload(
    *,
    watchlist_model: dict[str, Any],
    watchlist: Path,
    provider: str | None,
    mode: str,
    interval: str,
    days: int,
    max_workers: int = 4,
) -> tuple[int, dict[str, Any]]:
    registry = default_provider_registry()
    scanned_at = datetime.now(UTC)
    symbols = tuple(watchlist_model["symbols"])
    price_provider = _watchlist_price_provider_preference(watchlist_model, provider)
    provider_mode = (
        _provider_mode_payload(mode)
        if price_provider is None
        else _explicit_provider_mode_payload(registry, price_provider)
    )
    results: list[dict[str, Any]] = []
    if not watchlist_model["enabled"]:
        skipped_symbols = [
            {
                "symbol": symbol,
                "status": "skipped",
                "reason": "watchlist is disabled",
            }
            for symbol in symbols
        ]
        failed_symbols: list[dict[str, Any]] = []
        ranked_setups: list[dict[str, Any]] = []
        return 0, _watchlist_report_payload(
            watchlist=watchlist,
            watchlist_model=watchlist_model,
            scanned_at=scanned_at,
            provider_mode=provider_mode,
            symbols=symbols,
            results=skipped_symbols,
            ranked_setups=ranked_setups,
            failed_symbols=failed_symbols,
            skipped_symbols=skipped_symbols,
        )

    exit_code = 0
    bounded_workers = max(1, min(max(1, max_workers), len(symbols)))
    results_by_symbol: dict[str, dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=bounded_workers) as executor:
        future_to_symbol = {
            executor.submit(
                _scan_symbol_result,
                registry,
                symbol=symbol,
                provider=price_provider,
                mode=mode,
                interval=interval,
                days=days,
                as_of=scanned_at,
            ): symbol
            for symbol in symbols
        }
        for future in as_completed(future_to_symbol):
            symbol = future_to_symbol[future]
            try:
                result = future.result()
            except Exception as exc:  # pragma: no cover - defensive provider isolation
                result = {
                    "symbol": symbol,
                    "status": "failed",
                    "error": redact_provider_diagnostic(
                        f"provider raised {type(exc).__name__}: {exc}"
                    ),
                }
            if result["status"] != "ok":
                exit_code = 1
            results_by_symbol[symbol] = result
    results = [results_by_symbol[symbol] for symbol in symbols]

    ranked_setups = _rank_scan_setups(results)
    failed_symbols = [result for result in results if result["status"] != "ok"]
    skipped_symbols = []

    return exit_code, _watchlist_report_payload(
        watchlist=watchlist,
        watchlist_model=watchlist_model,
        scanned_at=scanned_at,
        provider_mode=provider_mode,
        symbols=symbols,
        results=results,
        ranked_setups=ranked_setups,
        failed_symbols=failed_symbols,
        skipped_symbols=skipped_symbols,
    )


def _scan_symbol_result(
    registry: ProviderRegistry,
    *,
    symbol: str,
    provider: str | None,
    mode: str,
    interval: str,
    days: int,
    as_of: datetime,
) -> dict[str, Any]:
    try:
        report = _fetch_ta_report(
            registry,
            symbol=symbol,
            provider=provider,
            mode=mode,
            interval=interval,
            days=days,
            as_of=as_of,
        )
    except RuntimeError as exc:
        return {
            "symbol": symbol,
            "status": "failed",
            "error": redact_provider_diagnostic(str(exc)),
        }
    return {"symbol": symbol, "status": "ok", "summary": _scan_result_summary(report)}


def _rank_scan_setups(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    successful_results = [result for result in results if result["status"] == "ok"]

    def sort_key(result: dict[str, Any]) -> tuple[int, int, str]:
        summary = result["summary"]
        setup_quality_score = summary["setup_quality_score"]
        risk_score = summary["risk_score"]
        return (
            -int(setup_quality_score if setup_quality_score is not None else -1),
            int(risk_score if risk_score is not None else 101),
            str(summary["symbol"]),
        )

    return [
        {**result, "rank": rank}
        for rank, result in enumerate(sorted(successful_results, key=sort_key), start=1)
    ]


def _format_card_provenance_fact_lines(summary: dict[str, Any]) -> list[str]:
    """Return per-card provenance facts so each card is standalone."""

    if not summary["provenance"]:
        return ["- Provenance: unavailable"]
    return [
        _format_provenance_markdown_line(
            provenance,
            fallback_generated_at=summary["generated_at"],
            prefix="Provenance: ",
        )
        for provenance in summary["provenance"]
    ]


def _format_report_enhanced_fact_lines(summary: dict[str, Any]) -> list[str]:
    """Return provider-sourced enhanced facts for a watchlist signal card."""

    signal_card = summary.get("signal_card")
    if not isinstance(signal_card, dict):
        return []
    facts = signal_card.get("facts")
    if not isinstance(facts, dict):
        return []
    return _format_enhanced_fact_lines(facts)


def _format_report_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# SignalDesk watchlist report",
        "",
        (
            "- Schema version: "
            + chr(96)
            + str(payload.get("schema_version", WATCHLIST_REPORT_SCHEMA_VERSION))
            + chr(96)
        ),
        f"- Watchlist: `{payload['watchlist']}`",
        f"- Watchlist name: `{payload['watchlist_model']['name']}`",
        f"- Watchlist tags: `{', '.join(payload['watchlist_model']['tags']) or 'none'}`",
        f"- Asset class: `{payload['watchlist_model']['asset_class']}`",
        f"- Enabled: `{str(payload['watchlist_model']['enabled']).lower()}`",
        f"- Generated at: `{payload['scanned_at']}`",
        f"- Provider mode: `{payload['provider_mode']['mode']}`",
        f"- Price provider: `{payload['provider_mode']['price_provider']}`",
    ]
    summary = payload["summary"]
    lines.extend(
        [
            "- Symbols scanned: `{}`".format(summary["total"]),
            "- Successful setups: `{}`".format(summary["ok"]),
            "- Failed symbols: `{}`".format(summary["failed"]),
            "- Skipped symbols: `{}`".format(summary["skipped"]),
        ]
    )
    if payload["provider_mode"].get("unavailable_context"):
        lines.append("- Unavailable context:")
        for item in payload["provider_mode"]["unavailable_context"]:
            lines.append(f"  - {_unavailable_context_text(item)}")
    else:
        lines.append("- Unavailable context: none")
    lines.extend(_markdown_report_boundary_lines())
    lines.extend(
        [
            "",
            "| Rank | Symbol | Status | Provider | Latest close | Trend | Setup | Risk |",
            "| ---: | --- | --- | --- | ---: | --- | ---: | ---: |",
        ]
    )
    for result in payload["ranked_setups"]:
        summary = result["summary"]
        lines.append(
            f"| {result['rank']} | {summary['symbol']} | ok | {summary['provider']} | "
            f"{summary['latest_close']} | {summary['trend_regime']['regime']} | "
            f"{summary['setup_quality_score']} | {summary['risk_score']} |"
        )
    for result in payload["failed_symbols"]:
        lines.append(f"|  | {result['symbol']} | failed |  |  |  |  | {result['error']} |")
    for result in payload["skipped_symbols"]:
        lines.append(f"|  | {result['symbol']} | skipped |  |  |  |  | {result['reason']} |")

    lines.extend(["", "## Signal cards"])
    for result in payload["ranked_setups"]:
        summary = result["summary"]
        confirmation_level = _format_optional_level(summary["confirmation_level"])
        invalidation_level = _format_optional_level(summary["invalidation_level"])
        lines.extend(
            [
                "",
                f"### {summary['symbol']}",
                "",
                "#### Facts",
                f"- Provider: `{summary['provider']}`",
                f"- Timeframe: `{summary['interval']}`",
                f"- Latest close: `{summary['latest_close']}`",
                f"- Latest timestamp: `{summary['latest_timestamp']}`",
                f"- Generated at: `{summary['generated_at']}`",
                f"- Schema version: `{summary['schema_version']}`",
                *_format_card_provenance_fact_lines(summary),
                *_format_report_enhanced_fact_lines(summary),
                "",
                "#### Setup",
                "- What is the setup? `{}` trend regime with setup quality `{}` "
                "and risk `{}`.".format(
                    summary["trend_regime"]["regime"],
                    summary["setup_quality_score"],
                    summary["risk_score"],
                ),
                "- Why it matters: {}".format(summary["trend_regime"]["reason"]),
                "",
                "#### Deterministic signals",
                "- Trend regime: `{}` — {}".format(
                    summary["trend_regime"]["regime"], summary["trend_regime"]["reason"]
                ),
                f"- Confirmation level: `{confirmation_level}`",
                f"- Invalidation level: `{invalidation_level}`",
                f"- Setup quality score: `{summary['setup_quality_score']}`",
                f"- Risk score: `{summary['risk_score']}`",
            ]
        )
        lines.extend(_format_score_reason_lines(summary["score_breakdowns"]))
        lines.extend(
            [
                "",
                "#### Technical events",
                *_format_technical_event_lines(summary["technical_events"]),
                "",
                "#### Confirmation and invalidation",
                f"- What confirms it: `{confirmation_level}`",
                f"- What invalidates it: `{invalidation_level}`",
                "",
                "#### Risks",
            ]
        )
        if summary["risk_flags"]:
            for flag in summary["risk_flags"]:
                lines.append(
                    f"- `{flag['severity']}` `{flag['kind']}`: {flag['message']} "
                    f"(source: `{flag['source']}`)"
                )
        else:
            lines.append("- none")
        lines.extend(["", "#### Unavailable context"])
        if summary["unavailable_context"]:
            for item in summary["unavailable_context"]:
                lines.append(f"- {_unavailable_context_text(item)}")
        else:
            lines.append("- none")
        narrative = summary.get("narrative") or "unavailable"
        lines.extend(
            [
                "",
                "#### Optional narrative",
                "- LLM: " + chr(96) + str(summary["llm"]) + chr(96),
                f"- Narrative: {narrative}",
            ]
        )
    lines.append("")
    lines.append("## Provenance")
    for result in payload["results"]:
        if result["status"] != "ok":
            continue
        summary = result["summary"]
        for provenance in summary["provenance"]:
            lines.append(
                _format_provenance_markdown_line(
                    provenance,
                    fallback_generated_at=summary["generated_at"],
                    prefix=f"{summary['symbol']}: ",
                )
            )
    return "\n".join(lines) + "\n"


@app.command("report")
def report_watchlist(
    watchlist: Path = typer.Option(..., help="YAML watchlist containing a top-level symbols list."),  # noqa: B008
    provider: str | None = typer.Option(
        None,
        help="Registered price provider to use for every symbol. When omitted, SignalDesk uses --mode role resolution.",  # noqa: E501
    ),
    mode: str = typer.Option("default", help="Provider role mode: default or enhanced."),
    llm: str = typer.Option("none", help="LLM provider. Only 'none' is currently supported."),
    interval: str = typer.Option("1d", help="Historical candle interval."),
    days: int = typer.Option(120, min=1, help="Number of calendar days of history to request."),
    max_workers: int = typer.Option(
        4,
        min=1,
        max=16,
        help="Maximum concurrent symbol fetches for the watchlist report.",
    ),
    report_format: str = typer.Option(
        "markdown", "--format", help="Report format: markdown, table, or json."
    ),
) -> None:
    """Generate a deterministic report for a watchlist."""

    if llm.strip().lower() != "none":
        typer.echo("Only --llm none is currently supported.", err=True)
        raise typer.Exit(2)
    normalized_report_format = report_format.strip().lower()
    if normalized_report_format not in {"markdown", "md", "table", "json"}:
        typer.echo("--format must be 'markdown', 'table', or 'json'.", err=True)
        raise typer.Exit(2)
    try:
        watchlist_model = _load_watchlist_model(watchlist)
        exit_code, payload = _scan_watchlist_payload(
            watchlist_model=watchlist_model,
            watchlist=watchlist,
            provider=provider,
            mode=mode,
            interval=interval,
            days=days,
            max_workers=max_workers,
        )
    except (KeyError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc
    if normalized_report_format == "json":
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    elif normalized_report_format == "table":
        for line in _format_scan_table(payload):
            typer.echo(line)
    else:
        typer.echo(_format_report_markdown(payload), nl=False)
    if exit_code:
        raise typer.Exit(exit_code)


def _ta_table_report_values(report: dict[str, Any]) -> dict[str, Any]:
    """Return the flat TA table view from the canonical signal-card object."""

    card = extract_ta_signal_card(report)
    identity = card["identity"]
    facts = card["facts"]
    trend = card["trend"]
    moving_averages = trend["moving_averages"]
    momentum = trend["momentum"]
    volatility = trend["volatility"]
    volume = trend["volume"]
    regimes = trend["regimes"]
    levels = card["levels"]
    setup_scores = [
        item for item in card["score"]["breakdowns"] if item["category"] == "setup_quality"
    ]
    risk_scores = [item for item in card["score"]["breakdowns"] if item["category"] == "risk"]
    trend_regime = regimes["trend"]
    confirmation_level = _format_optional_level(levels["confirmation"])
    invalidation_level = _format_optional_level(levels["invalidation"])
    values = {
        "schema_version": identity["schema_version"],
        "symbol": identity["symbol"],
        "provider": facts["provider"],
        "interval": facts["interval"],
        "candles": facts["candles"],
        "latest_timestamp": facts["latest_timestamp"],
        "latest_close": facts["latest_close"],
        "generated_at": identity["generated_at"],
        "provenance_summary": _summarize_provenance(card["provenance"]),
        "enhanced_context_summary": _summarize_enhanced_context(facts),
        "setup": "{} trend; setup_quality={}; risk={}".format(
            trend_regime["regime"],
            setup_scores[0]["score"] if setup_scores else "unavailable",
            risk_scores[0]["score"] if risk_scores else "unavailable",
        ),
        "why_it_matters": trend_regime["reason"],
        "what_confirms": confirmation_level,
        "what_invalidates": invalidation_level,
        "risk_summary": _summarize_risk_flags(card["risk"]["flags"]),
        "unavailable_context_summary": _summarize_unavailable_context(card["unavailable_context"]),
        "sma_20": moving_averages["sma_20"],
        "ema_20": moving_averages["ema_20"],
        "rsi_14": momentum["rsi_14"],
        "macd": momentum["macd"],
        "macd_signal": momentum["macd_signal"],
        "macd_histogram": momentum["macd_histogram"],
        "atr_14": volatility["atr_14"],
        "volume_average_20": volume["volume_average_20"],
        "relative_volume_20": volume["relative_volume_20"],
        "trend_regime": _summarize_regime(regimes["trend"]),
        "volatility_regime": _summarize_regime(regimes["volatility"]),
        "volume_regime": _summarize_regime(regimes["volume"]),
        "technical_events": _summarize_technical_events(card["events"]),
        "latest_swing_high": _format_optional_table_level(levels["resistance"]),
        "latest_swing_low": _format_optional_table_level(levels["support"]),
        "confirmation_level": confirmation_level,
        "invalidation_level": invalidation_level,
        "llm": card["llm"],
    }
    return {key: values[key] for key in _TABLE_REPORT_KEYS}


def _summarize_provenance(provenance_items: list[dict[str, Any]]) -> str:
    """Return compact provenance for flat terminal table reports."""

    if not provenance_items:
        return "none"
    summary_lines = []
    for provenance in provenance_items[:3]:
        inputs = (
            ",".join(_flat_table_cell_text(item) for item in provenance.get("inputs", [])) or "none"
        )
        summary_lines.append(
            "{}:{}:{} inputs={} observations={}".format(
                _flat_table_cell_text(provenance.get("provider", "unknown")),
                _flat_table_cell_text(provenance.get("source", "unknown")),
                _flat_table_cell_text(provenance.get("timeframe", "unknown")),
                inputs,
                _flat_table_cell_text(provenance.get("observations", "unknown")),
            )
        )
    omitted_count = len(provenance_items) - 3
    if omitted_count > 0:
        summary_lines.append(f"{omitted_count} more provenance item(s) omitted")
    return "; ".join(summary_lines)


def _flat_table_cell_text(value: object) -> str:
    """Return text that cannot split terminal table rows or columns."""

    return str(value).replace(chr(9), chr(32)).replace(chr(13), chr(32)).replace(chr(10), chr(32))


def _resolve_ta_provider(
    registry: ProviderRegistry, *, provider: str | None, mode: str
) -> tuple[Any, dict[str, Any], tuple[dict[str, Any], ...]]:
    """Resolve the TA price provider and role metadata without network I/O."""

    explicit_provider = provider.strip() if provider is not None else ""
    if explicit_provider:
        market_data_provider = registry.get(explicit_provider)
        return (
            market_data_provider,
            {
                "mode": "explicit",
                "price_provider": market_data_provider.name,
                "fundamentals_provider": None,
                "catalyst_provider": None,
                "llm_provider": None,
            },
            (),
        )

    provider_mode, unavailable_context = resolve_provider_mode(
        registry, mode=mode, role_config=_provider_role_config_from_env()
    )
    return (
        registry.get(provider_mode.price_provider),
        {
            "mode": provider_mode.mode,
            "price_provider": provider_mode.price_provider,
            "fundamentals_provider": provider_mode.fundamentals_provider,
            "catalyst_provider": provider_mode.catalyst_provider,
            "llm_provider": provider_mode.llm_provider,
        },
        tuple(
            {
                "context_type": item.context_type,
                "reason": item.reason,
                "provider": item.provider,
                "details": item.details,
            }
            for item in unavailable_context
        ),
    )


_TABLE_REPORT_KEYS = (
    "schema_version",
    "symbol",
    "provider",
    "interval",
    "candles",
    "latest_timestamp",
    "latest_close",
    "generated_at",
    "provenance_summary",
    "enhanced_context_summary",
    "setup",
    "why_it_matters",
    "what_confirms",
    "what_invalidates",
    "risk_summary",
    "unavailable_context_summary",
    "sma_20",
    "ema_20",
    "rsi_14",
    "macd",
    "macd_signal",
    "macd_histogram",
    "atr_14",
    "volume_average_20",
    "relative_volume_20",
    "trend_regime",
    "volatility_regime",
    "volume_regime",
    "technical_events",
    "latest_swing_high",
    "latest_swing_low",
    "confirmation_level",
    "invalidation_level",
    "llm",
)


def _enhanced_context_payloads(
    *, registry: ProviderRegistry, symbol: Symbol, provider_mode: dict[str, Any], as_of: datetime
) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    provenance: list[dict[str, Any]] = []
    unavailable_context: list[dict[str, Any]] = []

    fundamentals_provider = provider_mode.get("fundamentals_provider")
    if fundamentals_provider:
        result = _call_enhanced_context_provider(
            registry,
            provider_name=str(fundamentals_provider),
            method_name="get_fundamental_context",
            symbol=symbol,
        )
        if result.ok and result.data is not None:
            facts["fundamentals"] = _fundamental_context_payload(result.data)
            provenance.append(
                _context_provenance_payload(
                    provider=result.provider,
                    source="fundamental_context",
                    symbol=symbol,
                    generated_at=as_of,
                    observations=1,
                    warnings=_context_timestamp_warnings(
                        label="fundamental context",
                        timestamp=result.data.generated_at,
                        as_of=as_of,
                    ),
                )
            )
        else:
            unavailable_context.append(
                _context_unavailable_payload(
                    "fundamentals", str(fundamentals_provider), result.error
                )
            )

    catalyst_provider = provider_mode.get("catalyst_provider")
    if catalyst_provider:
        result = _call_enhanced_context_provider(
            registry,
            provider_name=str(catalyst_provider),
            method_name="get_catalyst_context",
            symbol=symbol,
        )
        if result.ok and result.data is not None:
            catalyst_payload = _catalyst_context_payload(result.data)
            facts["catalysts"] = catalyst_payload
            provenance.append(
                _context_provenance_payload(
                    provider=result.provider,
                    source="catalyst_context",
                    symbol=symbol,
                    generated_at=as_of,
                    observations=len(catalyst_payload["events"]),
                    warnings=_context_timestamp_warnings(
                        label="latest catalyst context",
                        timestamp=_latest_catalyst_timestamp(result.data),
                        as_of=as_of,
                    ),
                )
            )
        else:
            unavailable_context.append(
                _context_unavailable_payload("catalyst", str(catalyst_provider), result.error)
            )

    return {
        "facts": facts,
        "provenance": provenance,
        "unavailable_context": tuple(unavailable_context),
    }


def _call_enhanced_context_provider(
    registry: ProviderRegistry, *, provider_name: str, method_name: str, symbol: Symbol
) -> ProviderResult[Any]:
    try:
        provider = registry.get(provider_name)
    except KeyError as exc:
        return ProviderResult.failure(provider=provider_name, error=str(exc))
    method = getattr(provider, method_name, None)
    if method is None:
        return ProviderResult.failure(
            provider=provider_name, error=f"provider does not implement {method_name}"
        )
    result = method(symbol)
    if not isinstance(result, ProviderResult):
        return ProviderResult.failure(
            provider=provider_name, error="provider returned invalid context"
        )
    return result


def _context_unavailable_payload(
    context_type: str, provider_name: str, reason: str | None
) -> dict[str, Any]:
    return {
        "context_type": context_type,
        "reason": redact_provider_diagnostic(reason or "provider returned no context"),
        "provider": provider_name,
    }


def _latest_catalyst_timestamp(context: Any) -> datetime | None:
    timestamps = [
        event.published_at
        for event in getattr(context, "events", ())
        if getattr(event, "published_at", None) is not None
    ]
    return max(timestamps) if timestamps else getattr(context, "generated_at", None)


def _context_timestamp_warnings(
    *, label: str, timestamp: datetime | None, as_of: datetime
) -> tuple[str, ...]:
    if timestamp is None:
        return (f"{label} timestamp is unavailable",)
    if as_of - timestamp > ENHANCED_CONTEXT_STALE_AFTER:
        return (f"{label} timestamp is stale: {timestamp.isoformat()}",)
    return ()


def _context_provenance_payload(
    *,
    provider: str,
    source: str,
    symbol: Symbol,
    generated_at: datetime,
    observations: int,
    warnings: tuple[str, ...] = (),
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "provider": provider,
        "source": source,
        "timeframe": "point_in_time",
        "inputs": [symbol.ticker],
        "generated_at": generated_at.isoformat(),
        "observations": observations,
    }
    if warnings:
        payload["warnings"] = list(warnings)
    return payload


def _optional_decimal_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return _decimal_text(value)
    return str(value)


def _fundamental_context_payload(context: Any) -> dict[str, Any]:
    return {
        "symbol": context.symbol.ticker,
        "provider": context.provider,
        "generated_at": context.generated_at.isoformat(),
        "company_name": context.company_name,
        "exchange": context.exchange,
        "industry": context.industry,
        "sector": context.sector,
        "market_cap": context.market_cap,
        "currency": context.currency,
        "price": _optional_decimal_text(context.price),
        "beta": _optional_decimal_text(context.beta),
        "pe_ratio": _optional_decimal_text(context.pe_ratio),
        "eps": _optional_decimal_text(context.eps),
        "source_url": context.source_url,
    }


def _catalyst_context_payload(context: Any) -> dict[str, Any]:
    return {
        "symbol": context.symbol.ticker,
        "provider": context.provider,
        "generated_at": context.generated_at.isoformat(),
        "events": [
            {
                "headline": event.headline,
                "provider": event.provider,
                "published_at": event.published_at.isoformat() if event.published_at else None,
                "source": event.source,
                "url": event.url,
                "summary": event.summary,
            }
            for event in context.events
        ],
    }


def _technical_analysis_report(
    *,
    symbol: Symbol,
    provider_name: str,
    candles: tuple[Candle, ...],
    interval: str,
    provider_mode: dict[str, Any],
    as_of: datetime,
    mode_unavailable_context: tuple[dict[str, Any], ...] = (),
    enhanced_facts: dict[str, Any] | None = None,
    enhanced_provenance: list[dict[str, Any]] | None = None,
    enhanced_unavailable_context: tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    closes = tuple(candle.close for candle in candles)
    sma_20 = simple_moving_average(closes, period=20)[-1]
    ema_20 = exponential_moving_average(closes, period=20)[-1]
    rsi_14 = relative_strength_index(closes, period=14)[-1]
    macd_result = macd(closes)
    atr_14 = average_true_range(candles, period=14)[-1]
    volume_average_20 = volume_moving_average(candles, period=20)[-1]
    relative_volume_20 = relative_volume(candles, period=20)[-1]
    trend_regime = classify_trend_regime(closes)
    volatility_regime = classify_volatility_regime(candles)
    volume_regime = classify_volume_regime(candles)
    technical_events = (
        *detect_moving_average_cross_events(candles),
        *detect_breakout_breakdown_events(candles),
        *detect_trend_regime_shift_events(candles),
        *detect_relative_volume_spike_events(candles),
        *detect_overextension_events(candles, atr_multiple=Decimal("7")),
        *detect_volatility_regime_events(candles),
    )
    latest_swing_high = _latest_level(detect_swing_highs(candles))
    latest_swing_low = _latest_level(detect_swing_lows(candles))
    fibonacci_levels = _fibonacci_level_payloads(
        latest_swing_low=latest_swing_low, latest_swing_high=latest_swing_high
    )
    setup_levels = derive_confirmation_invalidation_levels(candles)
    latest_candle = candles[-1]

    facts = {
        "symbol": symbol.ticker,
        "provider": provider_name,
        "interval": interval,
        "candles": len(candles),
        "data_start": candles[0].timestamp.isoformat(),
        "data_end": latest_candle.timestamp.isoformat(),
        "latest_timestamp": latest_candle.timestamp.isoformat(),
        "latest_close": _decimal_text(latest_candle.close),
        "latest_volume": latest_candle.volume,
        **(enhanced_facts or {}),
    }
    indicators = {
        "sma_20": _decimal_text(sma_20),
        "ema_20": _decimal_text(ema_20),
        "rsi_14": _decimal_text(rsi_14),
        "macd": _decimal_text(macd_result.macd_line[-1]),
        "macd_signal": _decimal_text(macd_result.signal_line[-1]),
        "macd_histogram": _decimal_text(macd_result.histogram[-1]),
        "atr_14": _decimal_text(atr_14),
        "volume_average_20": _decimal_text(volume_average_20),
        "relative_volume_20": _decimal_text(relative_volume_20),
    }
    swing_levels = {
        "latest_swing_high": latest_swing_high,
        "latest_swing_low": latest_swing_low,
    }
    regimes = {
        "trend": _regime_payload(trend_regime),
        "volatility": _regime_payload(volatility_regime),
        "volume": _regime_payload(volume_regime),
    }
    setup = {
        "confirmation_level": _setup_level(setup_levels.confirmation),
        "invalidation_level": _setup_level(setup_levels.invalidation),
    }
    events = tuple(_technical_event_payload(event) for event in technical_events)

    unavailable_context = [
        *mode_unavailable_context,
        *enhanced_unavailable_context,
    ]
    fundamentals_already_unavailable = any(
        item["context_type"] == "fundamentals" for item in unavailable_context
    )
    if "fundamentals" not in facts and not fundamentals_already_unavailable:
        unavailable_context.append(
            {
                "context_type": "fundamentals",
                "reason": "not available in the default technical-analysis CLI path",
                "provider": provider_name,
            }
        )
    catalyst_already_unavailable = any(
        item["context_type"] == "catalyst" for item in unavailable_context
    )
    if "catalysts" not in facts and not catalyst_already_unavailable:
        unavailable_context.append(
            {
                "context_type": "catalyst",
                "reason": "not available in the default technical-analysis CLI path",
                "provider": provider_name,
            }
        )
    unavailable_context.append(
        {
            "context_type": "llm_explanation",
            "reason": "--llm none selected; narrative explanations are disabled",
            "provider": None,
        }
    )
    fundamentals_unavailable = any(
        item["context_type"] == "fundamentals" for item in unavailable_context
    )
    risks = _risk_payloads(
        assess_technical_analysis_risks(
            candle_count=len(candles),
            latest_candle_timestamp=latest_candle.timestamp,
            as_of=as_of,
            trend_regime=trend_regime,
            volatility_regime=volatility_regime,
            volume_regime=volume_regime,
            technical_events=technical_events,
            setup_levels=setup_levels,
            fundamentals_unavailable=fundamentals_unavailable,
        )
    )
    scores = _score_payloads(
        score_technical_analysis(
            candle_count=len(candles),
            latest_candle_timestamp=latest_candle.timestamp,
            as_of=as_of,
            trend_regime=trend_regime,
            volatility_regime=volatility_regime,
            volume_regime=volume_regime,
            technical_events=technical_events,
            setup_levels=setup_levels,
            fundamentals_unavailable=fundamentals_unavailable,
        )
    )

    identity = {
        "symbol": symbol.ticker,
        "timeframe": interval,
        "generated_at": as_of.isoformat(),
        "schema_version": "signaldesk.ta.v1",
    }
    trend = {
        "moving_averages": {
            "sma_20": indicators["sma_20"],
            "ema_20": indicators["ema_20"],
        },
        "momentum": {
            "rsi_14": indicators["rsi_14"],
            "macd": indicators["macd"],
            "macd_signal": indicators["macd_signal"],
            "macd_histogram": indicators["macd_histogram"],
        },
        "volatility": {
            "atr_14": indicators["atr_14"],
        },
        "volume": {
            "volume_average_20": indicators["volume_average_20"],
            "relative_volume_20": indicators["relative_volume_20"],
        },
        "regimes": regimes,
    }
    levels: dict[str, Any] = {
        "support": swing_levels["latest_swing_low"],
        "resistance": swing_levels["latest_swing_high"],
        "fibonacci": fibonacci_levels,
        "confirmation": setup["confirmation_level"],
        "invalidation": setup["invalidation_level"],
    }
    provenance = [
        {
            "provider": provider_name,
            "source": "historical_candles",
            "timeframe": interval,
            "inputs": [symbol.ticker],
            "generated_at": as_of.isoformat(),
            "observations": len(candles),
        },
        *(enhanced_provenance or []),
    ]
    risk = {
        "flags": risks,
        "unavailable_context": unavailable_context,
    }
    score = {
        "breakdowns": scores,
    }
    return assemble_ta_signal_card_report(
        schema_version="signaldesk.ta.v1",
        identity=identity,
        provider_mode=provider_mode,
        facts=facts,
        trend=trend,
        levels=levels,
        events=events,
        risk=risk,
        score=score,
        provenance=provenance,
        unavailable_context=unavailable_context,
        deterministic_signals={
            "indicators": indicators,
            "regimes": regimes,
            "events": events,
            "swing_levels": swing_levels,
            "fibonacci_levels": fibonacci_levels,
            "setup_levels": setup,
        },
        flat_fields={
            "symbol": facts["symbol"],
            "provider": facts["provider"],
            "interval": facts["interval"],
            "candles": facts["candles"],
            "latest_timestamp": facts["latest_timestamp"],
            "latest_close": facts["latest_close"],
            "sma_20": indicators["sma_20"],
            "ema_20": indicators["ema_20"],
            "rsi_14": indicators["rsi_14"],
            "macd": indicators["macd"],
            "macd_signal": indicators["macd_signal"],
            "macd_histogram": indicators["macd_histogram"],
            "atr_14": indicators["atr_14"],
            "volume_average_20": indicators["volume_average_20"],
            "relative_volume_20": indicators["relative_volume_20"],
            "trend_regime": regimes["trend"],
            "volatility_regime": regimes["volatility"],
            "volume_regime": regimes["volume"],
            "technical_events": events,
            "latest_swing_high": swing_levels["latest_swing_high"],
            "latest_swing_low": swing_levels["latest_swing_low"],
            "confirmation_level": setup["confirmation_level"],
            "invalidation_level": setup["invalidation_level"],
        },
    )


def _fibonacci_level_payloads(
    *, latest_swing_low: dict[str, Any] | None, latest_swing_high: dict[str, Any] | None
) -> list[dict[str, Any]]:
    if latest_swing_low is None or latest_swing_high is None:
        return []

    low = Decimal(latest_swing_low["price"])
    high = Decimal(latest_swing_high["price"])
    if low >= high:
        return []

    levels = calculate_fibonacci_retracement_levels(low, high)
    return [_fibonacci_level_payload(level) for level in levels]


def _fibonacci_level_payload(level: FibonacciRetracementLevel) -> dict[str, Any]:
    return {
        "ratio": _decimal_text(level.ratio),
        "percent": _decimal_text(level.percent),
        "price": _decimal_text(level.price),
        "direction": level.direction,
        "swing_start": _decimal_text(level.swing_start),
        "swing_end": _decimal_text(level.swing_end),
        "source_rule": "latest_swing_low_to_high_retracement",
    }


def _risk_payloads(flags: tuple[RiskFlag, ...]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "kind": flag.kind,
            "severity": flag.severity,
            "message": flag.message,
            "source": flag.source,
        }
        for flag in flags
    )


def _score_payloads(scores: tuple[ScoreBreakdown, ...]) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "category": score.category,
            "score": _decimal_text(score.score),
            "reasons": [
                {
                    "code": reason.code,
                    "message": reason.message,
                    "source": reason.source,
                    "weight": _decimal_text(reason.weight),
                }
                for reason in score.reasons
            ],
        }
        for score in scores
    )


def _latest_level(points: tuple[Any, ...]) -> dict[str, Any] | None:
    if not points:
        return None
    point = points[-1]
    return {
        "candle_index": point.candle_index,
        "timestamp": point.timestamp.isoformat(),
        "price": _decimal_text(point.price),
    }


def _regime_payload(regime: Any) -> dict[str, Any]:
    return {
        "regime": regime.regime,
        "source_rule": regime.source_rule,
        "reason": regime.reason,
    }


def _setup_level(level: ConfirmationInvalidationLevel | None) -> dict[str, Any] | None:
    if level is None:
        return None
    return {
        "kind": level.kind,
        "price": _decimal_text(level.price),
        "source_rule": level.source_rule,
        "source_level": level.source_level,
        "reason": level.reason,
    }


def _technical_event_payload(event: Any) -> dict[str, Any]:
    return {
        "event_type": event.event_type,
        "timestamp": event.timestamp.isoformat(),
        "candle_index": event.candle_index,
        "severity": event.severity,
        "source_rule": event.source_rule,
        "source_indicators": list(event.source_indicators),
        "reason": event.reason,
        "price": _decimal_text(event.price),
        "invalidation_condition": event.invalidation_condition,
    }


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _provider_health_payload(provider_name: str, result: ProviderResult[str]) -> dict[str, Any]:
    status = "ok" if result.ok else "failed"
    detail = result.data if result.ok else result.error
    return {
        "provider": provider_name,
        "status": status,
        "result": redact_provider_diagnostic(detail or ""),
        "warnings": tuple(redact_provider_diagnostic(warning) for warning in result.warnings),
    }


def _format_provider_health(provider_name: str, result: ProviderResult[str]) -> str:
    payload = _provider_health_payload(provider_name, result)
    return f"{payload['provider']}\t{payload['status']}\t{payload['result']}"


def _unknown_provider_capability(provider_name: str) -> dict[str, Any]:
    return {
        "provider": provider_name,
        "tier": "unknown",
        "role": "unknown",
        "realtime": False,
        "historical": False,
        "asset_classes": [],
        "intervals": [],
        "credential_state": "unknown",
        "live_check": False,
        "max_history_days": None,
        "rate_limit_per_minute": None,
    }


def _provider_capabilities_payload(
    registry: ProviderRegistry,
    *,
    role: str | None = None,
    tier: str | None = None,
    credential_state: str | None = None,
    live_check_only: bool = False,
) -> tuple[dict[str, Any], ...]:
    payload: list[dict[str, Any]] = []
    normalized_role = _normalize_optional_filter(role)
    normalized_tier = _normalize_optional_filter(tier)
    normalized_credential_state = _normalize_optional_filter(credential_state)
    for provider in registry.list():
        try:
            capabilities = provider.capabilities()
        except Exception:
            unknown_payload = _unknown_provider_capability(provider.name)
            if _provider_capability_matches(
                unknown_payload,
                role=normalized_role,
                tier=normalized_tier,
                credential_state=normalized_credential_state,
                live_check_only=live_check_only,
            ):
                payload.append(unknown_payload)
            continue
        if not capabilities:
            unknown_payload = _unknown_provider_capability(provider.name)
            if _provider_capability_matches(
                unknown_payload,
                role=normalized_role,
                tier=normalized_tier,
                credential_state=normalized_credential_state,
                live_check_only=live_check_only,
            ):
                payload.append(unknown_payload)
            continue
        for capability in capabilities:
            provider_capability = {
                "provider": provider.name,
                "tier": capability.provider_tier,
                "role": capability.data_role,
                "realtime": capability.supports_realtime,
                "historical": capability.supports_historical,
                "asset_classes": sorted(capability.supported_asset_classes),
                "intervals": sorted(capability.supported_intervals),
                "credential_state": capability.credential_state,
                "live_check": capability.live_check_suitable,
                "max_history_days": capability.max_history_days,
                "rate_limit_per_minute": capability.rate_limit_per_minute,
            }
            if _provider_capability_matches(
                provider_capability,
                role=normalized_role,
                tier=normalized_tier,
                credential_state=normalized_credential_state,
                live_check_only=live_check_only,
            ):
                payload.append(provider_capability)
    return tuple(payload)


def _normalize_optional_filter(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace(" ", "_")
    return normalized or None


def _provider_capability_matches(
    capability: dict[str, Any],
    *,
    role: str | None,
    tier: str | None,
    credential_state: str | None,
    live_check_only: bool,
) -> bool:
    if role is not None and capability["role"] != role:
        return False
    if tier is not None and capability["tier"] != tier:
        return False
    if credential_state is not None and capability["credential_state"] != credential_state:
        return False
    if live_check_only and not capability["live_check"]:
        return False
    return True


def _format_provider_capabilities(
    registry: ProviderRegistry,
    *,
    role: str | None = None,
    tier: str | None = None,
    credential_state: str | None = None,
    live_check_only: bool = False,
) -> tuple[str, ...]:
    lines = [
        "provider\ttier\trole\trealtime\thistorical\tasset_classes\tintervals\tcredential_state\tlive_check\tmax_history_days\trate_limit_per_minute"
    ]
    for capability in _provider_capabilities_payload(
        registry,
        role=role,
        tier=tier,
        credential_state=credential_state,
        live_check_only=live_check_only,
    ):
        asset_classes = ",".join(capability["asset_classes"])
        intervals = ",".join(capability["intervals"])
        lines.append(
            f"{capability['provider']}\t"
            f"{capability['tier']}\t"
            f"{capability['role']}\t"
            f"{str(capability['realtime']).lower()}\t"
            f"{str(capability['historical']).lower()}\t"
            f"{asset_classes}\t"
            f"{intervals}\t"
            f"{capability['credential_state']}\t"
            f"{str(capability['live_check']).lower()}\t"
            f"{_optional_int_text(capability['max_history_days'])}\t"
            f"{_optional_int_text(capability['rate_limit_per_minute'])}"
        )
    return tuple(lines)


def _optional_int_text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _run_provider_health_checks(
    registry: ProviderRegistry,
    *,
    live_check_only: bool = False,
) -> tuple[int, tuple[dict[str, Any], ...]]:
    payload: list[dict[str, Any]] = []
    exit_code = 0
    safe_provider_names = _live_check_provider_names(registry) if live_check_only else None
    for provider in registry.list():
        if safe_provider_names is not None and provider.name not in safe_provider_names:
            continue
        try:
            result = provider.health_check()
        except Exception:
            result = ProviderResult.failure(
                provider=provider.name,
                error="health check raised an exception",
            )
        payload.append(_provider_health_payload(provider.name, result))
        if not result.ok:
            exit_code = 1
    return exit_code, tuple(payload)


def _live_check_provider_names(registry: ProviderRegistry) -> frozenset[str]:
    """Return providers declaring at least one health/live-check-safe capability."""

    safe_names: set[str] = set()
    for provider in registry.list():
        try:
            capabilities = provider.capabilities()
        except Exception:
            continue
        if any(capability.live_check_suitable for capability in capabilities):
            safe_names.add(provider.name)
    return frozenset(safe_names)


def _provider_mode_payload(mode: str) -> dict[str, Any]:
    provider_mode, unavailable_context = resolve_provider_mode(
        default_provider_registry(), mode=mode, role_config=_provider_role_config_from_env()
    )
    return {
        "mode": provider_mode.mode,
        "price_provider": provider_mode.price_provider,
        "fundamentals_provider": provider_mode.fundamentals_provider,
        "catalyst_provider": provider_mode.catalyst_provider,
        "llm_provider": provider_mode.llm_provider,
        "unavailable_context": [
            {
                "context_type": item.context_type,
                "reason": item.reason,
                "provider": item.provider,
                "details": item.details,
            }
            for item in unavailable_context
        ],
    }


def _provider_role_config_from_env() -> ProviderRoleConfig:
    return ProviderRoleConfig(
        default_price_provider=os.getenv("SIGNALDESK_DEFAULT_PRICE_PROVIDER"),
        enhanced_price_provider=os.getenv("SIGNALDESK_ENHANCED_PRICE_PROVIDER"),
        enhanced_fundamentals_provider=os.getenv("SIGNALDESK_ENHANCED_FUNDAMENTALS_PROVIDER"),
        enhanced_catalyst_provider=os.getenv("SIGNALDESK_ENHANCED_CATALYST_PROVIDER"),
    )


def _format_provider_mode(payload: dict[str, Any]) -> tuple[str, ...]:
    lines = ["role\tprovider"]
    lines.append(f"mode\t{payload['mode']}")
    lines.append(f"price\t{payload['price_provider']}")
    lines.append(f"fundamentals\t{payload['fundamentals_provider'] or 'unavailable'}")
    lines.append(f"catalyst\t{payload['catalyst_provider'] or 'unavailable'}")
    lines.append(f"llm\t{payload['llm_provider'] or 'none'}")
    for item in payload["unavailable_context"]:
        lines.append(
            f"unavailable:{item['context_type']}\t{item['provider'] or 'none'}: {item['reason']}"
        )
    return tuple(lines)


@providers_app.command("mode")
def providers_mode(
    mode: str = typer.Option("default", help="Provider mode to resolve: default or enhanced."),
    output: str = typer.Option("table", help="Output format: table or json."),
) -> None:
    """Resolve provider roles for default or enhanced mode without network I/O."""

    output_format = output.strip().lower()
    if output_format not in {"table", "json"}:
        typer.echo("--output must be 'table' or 'json'.", err=True)
        raise typer.Exit(2)
    try:
        payload = _provider_mode_payload(mode)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    if output_format == "json":
        typer.echo(json.dumps(payload, indent=2))
        return

    for line in _format_provider_mode(payload):
        typer.echo(line)


@providers_app.command("list")
def providers_list(
    output: str = typer.Option("table", help="Output format: table or json."),
    role: str | None = typer.Option(
        None,
        help="Only show capabilities for a data role such as price, fundamentals, or catalyst.",
    ),
    tier: str | None = typer.Option(
        None, help="Only show capabilities for a provider tier: default or enhanced."
    ),
    credential_state: str | None = typer.Option(
        None,
        help=(
            "Only show capabilities with this credential state, such as "
            "not_required or not_configured."
        ),
    ),
    live_check_only: bool = typer.Option(
        False,
        help="Only show capabilities that are safe for provider health/live checks.",
    ),
) -> None:
    """List registered market-data providers and declared capabilities."""

    output_format = output.strip().lower()
    if output_format not in {"table", "json"}:
        typer.echo("--output must be 'table' or 'json'.", err=True)
        raise typer.Exit(2)

    registry = default_provider_registry()
    if output_format == "json":
        typer.echo(
            json.dumps(
                {
                    "providers": _provider_capabilities_payload(
                        registry,
                        role=role,
                        tier=tier,
                        credential_state=credential_state,
                        live_check_only=live_check_only,
                    )
                },
                indent=2,
            )
        )
        return

    for line in _format_provider_capabilities(
        registry,
        role=role,
        tier=tier,
        credential_state=credential_state,
        live_check_only=live_check_only,
    ):
        typer.echo(line)


@providers_app.command("check")
def providers_check(
    output: str = typer.Option("table", help="Output format: table or json."),
    live_check_only: bool = typer.Option(
        False,
        help="Only check providers that declare their health checks safe for live checks.",
    ),
) -> None:
    """Run safe local health checks for registered market-data providers."""

    output_format = output.strip().lower()
    if output_format not in {"table", "json"}:
        typer.echo("--output must be 'table' or 'json'.", err=True)
        raise typer.Exit(2)

    exit_code, provider_statuses = _run_provider_health_checks(
        default_provider_registry(), live_check_only=live_check_only
    )
    if output_format == "json":
        typer.echo(json.dumps({"providers": provider_statuses}, indent=2))
    else:
        typer.echo("provider\tstatus\tresult")
        for provider_status in provider_statuses:
            typer.echo(
                f"{provider_status['provider']}\t"
                f"{provider_status['status']}\t"
                f"{provider_status['result']}"
            )
    if exit_code:
        raise typer.Exit(exit_code)


if __name__ == "__main__":
    app()
