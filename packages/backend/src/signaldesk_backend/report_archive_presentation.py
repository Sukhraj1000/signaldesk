"""Renderer-facing report archive presentation adapter."""

from collections.abc import Iterable, Mapping
from typing import Any

REPORT_ARCHIVE_PRESENTATION_SCHEMA_VERSION = (
    "signaldesk.web.report_archive_presentation.v1"
)


def build_report_archive_presentation(
    reports: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Group canonical TA reports into renderer-only archive rows."""

    rows = [_report_row(report) for report in reports]
    rows.sort(
        key=lambda row: (row.get("generated_at") or "", row.get("symbol") or ""),
        reverse=True,
    )
    return {
        "schema_version": REPORT_ARCHIVE_PRESENTATION_SCHEMA_VERSION,
        "summary_tiles": {
            "total": len(rows),
            "with_unavailable_context": sum(
                1 for row in rows if row["unavailable_context_count"]
            ),
            "with_risk_flags": sum(1 for row in rows if row["risk_flag_count"]),
        },
        "report_rows": rows,
        "rendering_contract": {
            "source": "canonical TA report JSON",
            "no_dashboard_analysis": True,
            "empty_sections_mean_unavailable_or_not_emitted_by_backend": True,
        },
    }


def _report_row(report: Mapping[str, Any]) -> dict[str, Any]:
    _require_report_sections(report)
    signal_card = _mapping_section(report, "signal_card")
    identity = _mapping_section(signal_card, "identity")
    provider_mode = _mapping_section(signal_card, "provider_mode")
    facts = _mapping_section(signal_card, "facts")
    risk = _mapping_section(signal_card, "risk")
    score = _mapping_section(signal_card, "score")

    risk_flags = _required_mapping_items(risk, "flags", "TA report risk")
    score_breakdowns = _required_mapping_items(score, "breakdowns", "TA report score")
    unavailable_context = _required_mapping_items(
        signal_card, "unavailable_context", "TA report signal_card"
    )
    provenance = _required_mapping_items(signal_card, "provenance", "TA report signal_card")

    return {
        "symbol": identity.get("symbol") or facts.get("symbol"),
        "timeframe": identity.get("timeframe") or facts.get("interval"),
        "generated_at": identity.get("generated_at"),
        "schema_version": signal_card.get("schema_version") or report.get("schema_version"),
        "provider_badge": {
            "mode": provider_mode.get("mode"),
            "price_provider": provider_mode.get("price_provider") or facts.get("provider"),
        },
        "latest_close": facts.get("latest_close"),
        "score_summary": _score_summary(score_breakdowns),
        "risk_flag_count": len(risk_flags),
        "unavailable_context_count": len(unavailable_context),
        "provenance_rows": provenance,
        "value": signal_card,
    }


def _require_report_sections(report: Mapping[str, Any]) -> None:
    required = ("schema_version", "signal_card")
    missing = [section for section in required if section not in report]
    if missing:
        raise ValueError(f"TA report missing archive section(s): {', '.join(missing)}")


def _mapping_section(parent: Mapping[str, Any], section: str) -> Mapping[str, Any]:
    value = parent.get(section)
    if not isinstance(value, Mapping):
        raise ValueError(f"TA report {section} section must be a JSON object")
    return value


def _required_mapping_items(
    parent: Mapping[str, Any], section: str, parent_label: str
) -> list[dict[str, Any]]:
    if section not in parent:
        raise ValueError(f"{parent_label} {section} section is required")
    return _mapping_items(parent[section])


def _mapping_items(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [dict(value)]
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        raise ValueError("archive presentation sections must be JSON objects or lists")
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("archive presentation entries must be JSON objects")
        items.append(dict(item))
    return items


def _score_summary(value: object) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for item in _mapping_items(value):
        category = item.get("category")
        if category is not None:
            summary[str(category)] = item.get("score")
    return summary
