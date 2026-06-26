"""Renderer-facing provider status presentation adapter."""

from collections.abc import Iterable, Mapping
from typing import Any

PROVIDER_STATUS_PRESENTATION_SCHEMA_VERSION = (
    "signaldesk.web.provider_status_presentation.v1"
)


def build_provider_status_presentation(
    *,
    provider_mode: Mapping[str, Any],
    provider_capabilities: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Group provider capability facts for the dashboard provider-status view.

    The dashboard view should render provider resolution and declared capability
    facts that already exist in the backend/CLI adapter layer. It must not run
    live checks, read credentials, or infer provider availability beyond the
    canonical provider mode and capability payloads supplied here.
    """

    _require_provider_mode(provider_mode)
    capability_rows = [_capability_row(capability) for capability in provider_capabilities]
    return {
        "schema_version": PROVIDER_STATUS_PRESENTATION_SCHEMA_VERSION,
        "mode_summary": {
            "mode": provider_mode["mode"],
            "price_provider": provider_mode["price_provider"],
            "fundamentals_provider": provider_mode.get("fundamentals_provider"),
            "catalyst_provider": provider_mode.get("catalyst_provider"),
            "llm_provider": provider_mode.get("llm_provider"),
        },
        "provider_rows": capability_rows,
        "credential_sections": _group_by(capability_rows, "credential_state"),
        "role_sections": _group_by(capability_rows, "role"),
        "unavailable_context": [
            dict(item)
            for item in _iter_mapping_items(provider_mode.get("unavailable_context"))
        ],
    }


def _require_provider_mode(provider_mode: Mapping[str, Any]) -> None:
    required = ("mode", "price_provider", "unavailable_context")
    missing = [key for key in required if key not in provider_mode]
    if missing:
        raise ValueError(f"provider_mode missing presentation field(s): {', '.join(missing)}")


def _capability_row(capability: Mapping[str, Any]) -> dict[str, Any]:
    required = (
        "provider",
        "tier",
        "role",
        "credential_state",
        "live_check",
        "historical",
        "realtime",
    )
    missing = [key for key in required if key not in capability]
    if missing:
        raise ValueError(
            f"provider capability missing presentation field(s): {', '.join(missing)}"
        )
    return {
        "provider": capability["provider"],
        "tier": capability["tier"],
        "role": capability["role"],
        "credential_state": capability["credential_state"],
        "live_check": capability["live_check"],
        "historical": capability["historical"],
        "realtime": capability["realtime"],
        "asset_classes": list(capability.get("asset_classes") or []),
        "intervals": list(capability.get("intervals") or []),
        "max_history_days": capability.get("max_history_days"),
        "rate_limit_per_minute": capability.get("rate_limit_per_minute"),
    }


def _group_by(rows: Iterable[Mapping[str, Any]], key: str) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        label = str(row.get(key) or "unknown")
        groups.setdefault(label, []).append(dict(row))
    return [
        {"label": label, "providers": providers}
        for label, providers in sorted(groups.items())
    ]


def _iter_mapping_items(value: object) -> Iterable[Mapping[str, Any]]:
    if value is None:
        return ()
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        raise ValueError("provider_mode unavailable_context must be a list of JSON objects")
    items: list[Mapping[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError("provider_mode unavailable_context entries must be JSON objects")
        items.append(item)
    return tuple(items)
