"""Renderer-facing watchlist scan presentation adapter."""

from collections.abc import Iterable, Mapping
from typing import Any

from signaldesk_backend.signal_card_presentation import report_boundaries

WATCHLIST_SCAN_PRESENTATION_SCHEMA_VERSION = "signaldesk.web.watchlist_scan_presentation.v1"


def build_watchlist_scan_presentation(watchlist_report: Mapping[str, Any]) -> dict[str, Any]:
    """Group canonical watchlist report JSON into renderer-only dashboard sections."""

    _require_report_sections(watchlist_report)
    watchlist_model = _mapping_section(watchlist_report, "watchlist_model")
    provider_mode = _mapping_section(watchlist_report, "provider_mode")
    summary = _mapping_section(watchlist_report, "summary")
    run = _optional_mapping_section(watchlist_report, "run")

    return {
        "schema_version": WATCHLIST_SCAN_PRESENTATION_SCHEMA_VERSION,
        "headline": {
            "watchlist": watchlist_report.get("watchlist"),
            "name": watchlist_model.get("name"),
            "generated_at": watchlist_report.get("generated_at")
            or watchlist_report.get("scanned_at"),
            "symbols": _symbol_items(watchlist_report.get("symbols")),
        },
        "provider_badge": {
            "mode": provider_mode.get("mode"),
            "price_provider": provider_mode.get("price_provider"),
        },
        "summary_tiles": {
            "total": summary.get("total", 0),
            "ok": summary.get("ok", 0),
            "failed": summary.get("failed", 0),
            "skipped": summary.get("skipped", 0),
        },
        "run_summary": _run_summary(watchlist_report, run),
        "ranked_setup_rows": [
            _ranked_setup_row(result)
            for result in _mapping_items(watchlist_report.get("ranked_setups"))
        ],
        "signal_buckets": _signal_buckets(watchlist_report.get("signal_buckets")),
        "failed_rows": _status_rows(watchlist_report.get("failed_symbols")),
        "skipped_rows": _status_rows(watchlist_report.get("skipped_symbols")),
        "provider_unavailable_context": _mapping_items(
            provider_mode.get("unavailable_context")
        ),
        "provenance_rows": _mapping_items(watchlist_report.get("provenance")),
        "rendering_contract": {
            "source": "canonical watchlist report JSON",
            "no_dashboard_analysis": True,
            "empty_sections_mean_unavailable_or_not_emitted_by_backend": True,
            "report_boundaries_visible": True,
        },
        "report_boundaries": report_boundaries(),
    }


def _require_report_sections(watchlist_report: Mapping[str, Any]) -> None:
    """Require the canonical watchlist report sections used by renderers."""

    required = (
        "watchlist",
        "watchlist_model",
        "generated_at",
        "provider_mode",
        "symbols",
        "ranked_setups",
        "failed_symbols",
        "skipped_symbols",
        "summary",
        "provenance",
    )
    missing = [section for section in required if section not in watchlist_report]
    if missing:
        raise ValueError(
            f"watchlist report missing presentation section(s): {', '.join(missing)}"
        )


def _mapping_section(watchlist_report: Mapping[str, Any], section: str) -> Mapping[str, Any]:
    """Return a named report section after validating its JSON object shape."""

    value = watchlist_report[section]
    if not isinstance(value, Mapping):
        raise ValueError(f"watchlist report {section} section must be a JSON object")
    return value



def _optional_mapping_section(
    watchlist_report: Mapping[str, Any], section: str
) -> Mapping[str, Any]:
    """Return an optional report section after validating its JSON object shape."""

    if section not in watchlist_report:
        return {}
    value = watchlist_report[section]
    if not isinstance(value, Mapping):
        raise ValueError(f"watchlist report {section} section must be a JSON object")
    return value


def _run_summary(
    watchlist_report: Mapping[str, Any], run: Mapping[str, Any]
) -> dict[str, Any]:
    """Expose backend run identifiers and timing without dashboard recalculation."""

    return {
        "run_id": run.get("run_id") or watchlist_report.get("run_id"),
        "generated_at": run.get("generated_at")
        or watchlist_report.get("generated_at")
        or watchlist_report.get("scanned_at"),
        "duration_ms": run.get("duration_ms"),
        "symbol_count": run.get("symbol_count"),
        "failed_count": run.get("failed_count"),
        "skipped_count": run.get("skipped_count"),
        "max_workers": run.get("max_workers"),
    }

def _symbol_items(value: object) -> list[str]:
    """Validate and normalize the report symbol list for the presentation headline."""

    if value is None or isinstance(value, (str, bytes)):
        raise ValueError("watchlist report symbols section must be a list of symbols")
    if not isinstance(value, Iterable):
        raise ValueError("watchlist report symbols section must be a list of symbols")
    symbols: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("watchlist report symbol entries must be non-empty strings")
        symbols.append(item)
    return symbols

def _mapping_items(value: object) -> list[dict[str, Any]]:
    """Normalize an optional object-or-list section into JSON object rows."""

    if value is None:
        return []
    if isinstance(value, Mapping):
        return [dict(value)]
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        raise ValueError("watchlist presentation sections must be JSON objects or lists")
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("watchlist presentation section entries must be JSON objects")
        items.append(dict(item))
    return items


def _signal_buckets(value: object) -> dict[str, Any]:
    """Return deterministic watchlist signal buckets after validating row shapes."""

    if value is None:
        return {
            "schema_version": None,
            "source_rule": None,
            "decision_support_only": True,
            "buckets": [],
        }
    if not isinstance(value, Mapping):
        raise ValueError("watchlist report signal_buckets section must be a JSON object")
    buckets = _mapping_items(value.get("buckets"))
    return {
        "schema_version": value.get("schema_version"),
        "source_rule": value.get("source_rule"),
        "decision_support_only": value.get("decision_support_only"),
        "buckets": buckets,
    }


def _ranked_setup_row(result: Mapping[str, Any]) -> dict[str, Any]:
    """Build a renderer row from one backend-ranked watchlist setup result."""

    summary = result.get("summary")
    if not isinstance(summary, Mapping):
        raise ValueError("ranked watchlist setup rows must include a summary object")
    levels = summary.get("levels") if isinstance(summary.get("levels"), Mapping) else {}
    signal_state = summary.get("signal_state")
    signal_state_label = (
        signal_state.get("state")
        if isinstance(signal_state, Mapping) and isinstance(signal_state.get("state"), str)
        else None
    )
    return {
        "symbol": result.get("symbol") or summary.get("symbol"),
        "status": result.get("status"),
        "rank": result.get("rank"),
        "provider": summary.get("provider"),
        "latest_close": summary.get("latest_close"),
        "trend_regime": summary.get("trend_regime"),
        "signal_state": signal_state_label,
        "setup_quality_score": summary.get("setup_quality_score"),
        "risk_score": summary.get("risk_score"),
        "confirmation": (
            levels.get("confirmation") if isinstance(levels, Mapping) else None
        ) or summary.get("confirmation_level"),
        "invalidation": (
            levels.get("invalidation") if isinstance(levels, Mapping) else None
        ) or summary.get("invalidation_level"),
        "unavailable_context": _mapping_items(summary.get("unavailable_context")),
        "value": dict(result),
    }


def _status_rows(value: object) -> list[dict[str, Any]]:
    """Build renderer rows for failed or skipped watchlist symbols."""

    rows: list[dict[str, Any]] = []
    for item in _mapping_items(value):
        rows.append(
            {
                "symbol": item.get("symbol"),
                "status": item.get("status"),
                "reason": item.get("reason") or item.get("error"),
                "value": item,
            }
        )
    return rows
