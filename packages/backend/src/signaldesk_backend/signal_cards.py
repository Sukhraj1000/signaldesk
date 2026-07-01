"""Canonical signal-card payload assembly helpers."""

from collections.abc import Mapping
from typing import Any

_CANONICAL_SIGNAL_CARD_SECTIONS = (
    "identity",
    "provider_mode",
    "facts",
    "trend",
    "levels",
    "events",
    "risk",
    "score",
    "decision_support",
    "provenance",
    "unavailable_context",
    "llm",
    "narrative",
)


def assemble_ta_signal_card_report(
    *,
    schema_version: str,
    identity: dict[str, Any],
    provider_mode: dict[str, Any],
    facts: dict[str, Any],
    trend: dict[str, Any],
    levels: dict[str, Any],
    events: tuple[dict[str, Any], ...],
    risk: dict[str, Any],
    score: dict[str, Any],
    decision_support: dict[str, Any],
    provenance: list[dict[str, Any]],
    unavailable_context: list[dict[str, Any]],
    deterministic_signals: dict[str, Any],
    flat_fields: dict[str, Any],
    llm: str = "none",
    narrative: str | None = None,
) -> dict[str, Any]:
    """Return the renderer-facing TA report with one canonical signal card.

    CLI, API, dashboard, and reporting adapters should render the nested
    signal_card object rather than reassembling market facts, deterministic
    signals, risks, scores, provenance, unavailable context, or LLM metadata in
    adapter-specific shapes. Top-level aliases remain for the early CLI JSON
    contract while the canonical card is adopted by downstream renderers.
    """

    if schema_version != identity.get("schema_version"):
        raise ValueError("signal-card schema_version must match identity schema_version")

    _require_signal_card_sections(
        identity=identity,
        provider_mode=provider_mode,
        facts=facts,
        trend=trend,
        levels=levels,
        risk=risk,
        score=score,
        decision_support=decision_support,
    )
    signal_card: dict[str, Any] = {
        "identity": identity,
        "provider_mode": provider_mode,
        "facts": facts,
        "trend": trend,
        "levels": levels,
        "events": events,
        "risk": risk,
        "score": score,
        "decision_support": decision_support,
        "provenance": provenance,
        "unavailable_context": unavailable_context,
        "llm": llm,
        "narrative": narrative,
    }

    report = {
        "schema_version": identity["schema_version"],
        **flat_fields,
        "provider_mode": provider_mode,
        "identity": identity,
        "facts": facts,
        "trend": trend,
        "levels": levels,
        "events": events,
        "risk": risk,
        "score": score,
        "decision_support": decision_support,
        "signal_card": signal_card,
        "deterministic_signals": deterministic_signals,
        "risks": risk["flags"],
        "scores": score["breakdowns"],
        "provenance": provenance,
        "unavailable_context": unavailable_context,
        "llm": llm,
        "narrative": narrative,
    }
    validate_ta_signal_card_report(report)
    return report


def extract_ta_signal_card(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return the validated canonical signal card for renderers.

    CLI, API, dashboard, and reporting adapters should call this helper before
    rendering from a TA report. It keeps the boundary boring: deterministic
    assembly remains the source of truth, aliases are validated for drift, and
    consumers receive only the nested signal_card object instead of
    re-selecting facts, levels, risk, score, provenance, or unavailable context.
    """

    validate_ta_signal_card_report(report)
    signal_card = report["signal_card"]
    if not isinstance(signal_card, dict):
        raise ValueError("signal_card must be a JSON object")
    return signal_card


def validate_ta_signal_card_report(report: Mapping[str, Any]) -> None:
    """Validate renderer-facing signal-card alias consistency.

    Downstream CLI, API, dashboard, and reporting adapters should render the
    nested ``signal_card`` object. The top-level aliases remain during the v1
    migration, so this guard fails fast if a future assembler change updates a
    top-level section without keeping the canonical nested card in sync.
    """

    signal_card = report.get("signal_card")
    if not isinstance(signal_card, Mapping):
        raise ValueError("signal-card report must include a signal_card object")

    missing_report_sections = [
        section for section in _CANONICAL_SIGNAL_CARD_SECTIONS if section not in report
    ]
    if missing_report_sections:
        missing = ", ".join(missing_report_sections)
        raise ValueError(f"signal-card report missing top-level section(s): {missing}")

    missing_card_sections = [
        section for section in _CANONICAL_SIGNAL_CARD_SECTIONS if section not in signal_card
    ]
    if missing_card_sections:
        missing = ", ".join(missing_card_sections)
        raise ValueError(f"signal_card missing section(s): {missing}")

    drifted_sections = [
        section
        for section in _CANONICAL_SIGNAL_CARD_SECTIONS
        if signal_card[section] != report[section]
    ]
    if drifted_sections:
        drifted = ", ".join(drifted_sections)
        raise ValueError(f"signal_card section(s) drifted from top-level aliases: {drifted}")

    _validate_signal_card_identity_contract(report, signal_card)


def _validate_signal_card_identity_contract(
    report: Mapping[str, Any], signal_card: Mapping[str, Any]
) -> None:
    identity = signal_card["identity"]
    facts = signal_card["facts"]
    provider_mode = signal_card["provider_mode"]
    if not isinstance(identity, Mapping):
        raise ValueError("signal_card.identity must be a JSON object")
    if not isinstance(facts, Mapping):
        raise ValueError("signal_card.facts must be a JSON object")
    if not isinstance(provider_mode, Mapping):
        raise ValueError("signal_card.provider_mode must be a JSON object")

    schema_version = report.get("schema_version")
    identity_schema_version = identity.get("schema_version")
    if schema_version != "signaldesk.ta.v1" or identity_schema_version != schema_version:
        raise ValueError(
            "signal-card schema_version must be signaldesk.ta.v1 and match identity"
        )
    if facts.get("symbol") != identity.get("symbol"):
        raise ValueError("signal-card facts.symbol must match identity.symbol")
    if facts.get("interval") != identity.get("timeframe"):
        raise ValueError("signal-card facts.interval must match identity.timeframe")
    if provider_mode.get("price_provider") != facts.get("provider"):
        raise ValueError("signal-card price_provider must match facts.provider")
    if not isinstance(signal_card["risk"], Mapping):
        raise ValueError("signal_card.risk must be a JSON object")
    if signal_card["risk"].get("unavailable_context") != signal_card["unavailable_context"]:
        raise ValueError(
            "signal-card risk.unavailable_context must match unavailable_context"
        )


def _require_signal_card_sections(**sections: dict[str, Any]) -> None:
    for section_name, section in sections.items():
        if not section:
            raise ValueError(f"signal-card section {section_name} is required")

    if sections["identity"].get("schema_version") != "signaldesk.ta.v1":
        raise ValueError("signal-card identity must declare signaldesk.ta.v1")
    if "flags" not in sections["risk"] or "unavailable_context" not in sections["risk"]:
        raise ValueError("signal-card risk section must include flags and unavailable_context")
    if "breakdowns" not in sections["score"]:
        raise ValueError("signal-card score section must include breakdowns")
    if "signal_state" not in sections["decision_support"]:
        raise ValueError("signal-card decision_support section must include signal_state")
