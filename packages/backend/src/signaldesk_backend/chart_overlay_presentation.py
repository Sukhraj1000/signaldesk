"""Renderer-facing chart overlay presentation adapter."""

from collections.abc import Iterable, Mapping
from typing import Any

CHART_OVERLAY_PRESENTATION_SCHEMA_VERSION = "signaldesk.web.chart_overlay_presentation.v1"


def build_chart_overlay_presentation(signal_card: Mapping[str, Any]) -> dict[str, Any]:
    """Group canonical signal-card facts into renderer-only chart overlays."""

    if "signal_card" in signal_card:
        raise ValueError(
            "build_chart_overlay_presentation expects the nested signal_card, "
            "not the full TA report"
        )
    _require_card_sections(signal_card)

    identity = _mapping_section(signal_card, "identity")
    provider_mode = _mapping_section(signal_card, "provider_mode")
    facts = _mapping_section(signal_card, "facts")
    levels = _mapping_section(signal_card, "levels")
    trend = _mapping_section(signal_card, "trend")

    return {
        "schema_version": CHART_OVERLAY_PRESENTATION_SCHEMA_VERSION,
        "chart": {
            "symbol": identity.get("symbol") or facts.get("symbol"),
            "timeframe": identity.get("timeframe") or facts.get("interval"),
            "generated_at": identity.get("generated_at"),
            "price_provider": provider_mode.get("price_provider") or facts.get("provider"),
        },
        "horizontal_levels": _level_overlays(levels),
        "event_markers": _event_markers(signal_card.get("events")),
        "trend_badges": _trend_badges(trend.get("regimes")),
        "risk_markers": _risk_markers(_mapping_section(signal_card, "risk").get("flags")),
        "unavailable_context": _mapping_items(signal_card.get("unavailable_context")),
        "provenance_rows": _mapping_items(signal_card.get("provenance")),
        "rendering_contract": {
            "source": "canonical signal_card JSON",
            "no_dashboard_analysis": True,
            "empty_sections_mean_unavailable_or_not_emitted_by_backend": True,
        },
    }


def _require_card_sections(signal_card: Mapping[str, Any]) -> None:
    required = (
        "identity",
        "provider_mode",
        "facts",
        "trend",
        "levels",
        "events",
        "risk",
        "provenance",
        "unavailable_context",
    )
    missing = [section for section in required if section not in signal_card]
    if missing:
        raise ValueError(
            f"signal_card missing chart overlay section(s): {', '.join(missing)}"
        )


def _mapping_section(signal_card: Mapping[str, Any], section: str) -> Mapping[str, Any]:
    value = signal_card[section]
    if not isinstance(value, Mapping):
        raise ValueError(f"signal_card {section} section must be a JSON object")
    return value


def _level_overlays(levels: Mapping[str, Any]) -> list[dict[str, Any]]:
    overlays: list[dict[str, Any]] = []
    for section, role in (
        ("support", "support"),
        ("resistance", "resistance"),
        ("fibonacci", "fibonacci"),
        ("confirmation", "confirmation"),
        ("invalidation", "invalidation"),
    ):
        for item in _mapping_items(levels.get(section)):
            overlays.append(
                {
                    "label": _label(item),
                    "role": role,
                    "source_section": section,
                    "price": item.get("price"),
                    "emphasis": role in {"confirmation", "invalidation"},
                    "value": item,
                }
            )
    return overlays


def _event_markers(value: object) -> list[dict[str, Any]]:
    markers: list[dict[str, Any]] = []
    for item in _mapping_items(value):
        markers.append(
            {
                "label": _label(item),
                "kind": item.get("kind"),
                "status": item.get("status"),
                "timestamp": item.get("timestamp") or item.get("date"),
                "value": item,
            }
        )
    return markers


def _trend_badges(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, Mapping):
        raise ValueError("signal_card trend.regimes must be a JSON object when present")
    return [{"label": str(key), "value": regime} for key, regime in sorted(value.items())]


def _risk_markers(value: object) -> list[dict[str, Any]]:
    return [
        {"label": _label(item), "severity": item.get("severity"), "value": item}
        for item in _mapping_items(value)
    ]


def _mapping_items(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [dict(value)]
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        raise ValueError("chart overlay sections must be JSON objects or lists of JSON objects")
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("chart overlay section entries must be JSON objects")
        items.append(dict(item))
    return items


def _label(item: Mapping[str, Any]) -> str:
    label = item.get("kind") or item.get("category") or item.get("context_type")
    return str(label) if label is not None else "item"
