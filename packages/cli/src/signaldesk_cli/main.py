import json
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import typer
from signaldesk_backend import (
    Candle,
    ConfirmationInvalidationLevel,
    ProviderRegistry,
    ProviderResult,
    ProviderRoleConfig,
    ScoreBreakdown,
    Settings,
    Symbol,
    average_true_range,
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
    macd,
    redact_provider_diagnostic,
    relative_strength_index,
    relative_volume,
    resolve_provider_mode,
    score_technical_analysis,
    simple_moving_average,
    volume_moving_average,
)

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
    output: str = typer.Option("table", help="Output format: table or json."),
) -> None:
    """Fetch candles and run deterministic technical analysis for one symbol."""

    if llm.strip().lower() != "none":
        typer.echo("Only --llm none is currently supported.", err=True)
        raise typer.Exit(2)

    output_format = output.strip().lower()
    if output_format not in {"table", "json"}:
        typer.echo("--output must be 'table' or 'json'.", err=True)
        raise typer.Exit(2)

    registry = default_provider_registry()
    try:
        requested_symbol = Symbol(symbol)
        (
            market_data_provider,
            provider_mode_payload,
            mode_unavailable_context,
        ) = _resolve_ta_provider(registry, provider=provider, mode=mode)
    except (KeyError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(2) from exc

    end = datetime.now(UTC)
    start = end - timedelta(days=days)
    result = market_data_provider.get_historical_candles(
        requested_symbol, start=start, end=end, interval=interval
    )
    if not result.ok or not result.data:
        diagnostic = redact_provider_diagnostic(result.error or "provider returned no candles")
        typer.echo(f"{market_data_provider.name} failed: {diagnostic}", err=True)
        raise typer.Exit(1)

    report = _technical_analysis_report(
        symbol=requested_symbol,
        provider_name=market_data_provider.name,
        candles=result.data,
        interval=interval,
        provider_mode=provider_mode_payload,
        mode_unavailable_context=mode_unavailable_context,
    )
    if output_format == "json":
        typer.echo(json.dumps(report, indent=2, sort_keys=True))
        return

    for key in _TABLE_REPORT_KEYS:
        typer.echo(f"{key}	{report[key]}")


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


def _technical_analysis_report(
    *,
    symbol: Symbol,
    provider_name: str,
    candles: tuple[Candle, ...],
    interval: str,
    provider_mode: dict[str, Any],
    mode_unavailable_context: tuple[dict[str, Any], ...] = (),
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
    setup_levels = derive_confirmation_invalidation_levels(candles)
    latest_candle = candles[-1]

    facts = {
        "symbol": symbol.ticker,
        "provider": provider_name,
        "interval": interval,
        "candles": len(candles),
        "latest_timestamp": latest_candle.timestamp.isoformat(),
        "latest_close": _decimal_text(latest_candle.close),
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
        {
            "context_type": "fundamentals",
            "reason": "not available in the default technical-analysis CLI path",
            "provider": provider_name,
        },
        {
            "context_type": "llm_narrative",
            "reason": "--llm none selected; narrative explanations are disabled",
            "provider": None,
        },
    ]
    scores = _score_payloads(
        score_technical_analysis(
            candle_count=len(candles),
            trend_regime=trend_regime,
            volatility_regime=volatility_regime,
            technical_events=technical_events,
            setup_levels=setup_levels,
            fundamentals_unavailable=any(
                item["context_type"] == "fundamentals" for item in unavailable_context
            ),
        )
    )

    return {
        "schema_version": "signaldesk.ta.v1",
        "symbol": facts["symbol"],
        "provider": facts["provider"],
        "provider_mode": provider_mode,
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
        "facts": facts,
        "deterministic_signals": {
            "indicators": indicators,
            "regimes": regimes,
            "events": events,
            "swing_levels": swing_levels,
            "setup_levels": setup,
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
        "scores": scores,
        "provenance": [
            {
                "provider": provider_name,
                "source": "historical_candles",
                "timeframe": interval,
                "inputs": [symbol.ticker],
                "observations": len(candles),
            }
        ],
        "unavailable_context": unavailable_context,
        "llm": "none",
        "narrative": None,
    }


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
