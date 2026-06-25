
# Renderer-facing signal-card presentation adapter.

from collections.abc import Iterable, Mapping
from typing import Any

PRESENTATION_SCHEMA_VERSION = "signaldesk.web.signal_card_presentation.v1"


def build_signal_card_presentation(signal_card: Mapping[str, Any]) -> dict[str, Any]:
    _require_card_sections(signal_card)

    identity = _mapping_section(signal_card, "identity")
    provider_mode = _mapping_section(signal_card, "provider_mode")
    facts = _mapping_section(signal_card, "facts")
    levels = _mapping_section(signal_card, "levels")
    risk = _mapping_section(signal_card, "risk")
    score = _mapping_section(signal_card, "score")

    return {
        "schema_version": PRESENTATION_SCHEMA_VERSION,
        "headline": {
            "symbol": identity.get("symbol") or facts.get("symbol"),
            "timeframe": identity.get("timeframe") or facts.get("interval"),
            "generated_at": identity.get("generated_at"),
            "llm": signal_card.get("llm", "none"),
        },
        "provider_badge": {
            "mode": provider_mode.get("mode"),
            "price_provider": provider_mode.get("price_provider") or facts.get("provider"),
        },
        "level_groups": {
            "support": _display_items(levels.get("support")),
            "resistance": _display_items(levels.get("resistance")),
            "fibonacci": _display_items(levels.get("fibonacci")),
            "confirmation": _display_items(levels.get("confirmation")),
            "invalidation": _display_items(levels.get("invalidation")),
        },
        "event_rows": _display_items(signal_card.get("events")),
        "risk_panel": {
            "flags": _display_items(risk.get("flags")),
            "unavailable_context": _display_items(signal_card.get("unavailable_context")),
        },
        "score_rows": _display_items(score.get("breakdowns")),
        "provenance_rows": _display_items(signal_card.get("provenance")),
        "narrative": signal_card.get("narrative"),
    }


def _require_card_sections(signal_card: Mapping[str, Any]) -> None:
    required = (
        "identity",
        "provider_mode",
        "facts",
        "levels",
        "events",
        "risk",
        "score",
        "provenance",
        "unavailable_context",
    )
    missing = [section for section in required if section not in signal_card]
    if missing:
        raise ValueError(f"signal_card missing presentation section(s): {", ".join(missing)}")


def _mapping_section(signal_card: Mapping[str, Any], section: str) -> Mapping[str, Any]:
    value = signal_card[section]
    if not isinstance(value, Mapping):
        raise ValueError(f"signal_card {section} section must be a JSON object")
    return value


def _display_items(value: object) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [_display_item(value)]
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        return [_display_item(item) for item in value]
    return [{"label": "value", "value": value}]


def _display_item(item: object) -> dict[str, Any]:
    if isinstance(item, Mapping):
        label = (
            item.get("kind")
            or item.get("category")
            or item.get("context_type")
            or item.get("provider")
        )
        return {
            "label": str(label) if label is not None else "item",
            "value": dict(item),
        }
    return {"label": "value", "value": item}
