"""Canonical signal-card payload assembly helpers."""

from typing import Any


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

    _require_signal_card_sections(
        identity=identity,
        provider_mode=provider_mode,
        facts=facts,
        trend=trend,
        levels=levels,
        risk=risk,
        score=score,
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
        "provenance": provenance,
        "unavailable_context": unavailable_context,
        "llm": llm,
        "narrative": narrative,
    }

    return {
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
        "signal_card": signal_card,
        "deterministic_signals": deterministic_signals,
        "risks": risk["flags"],
        "scores": score["breakdowns"],
        "provenance": provenance,
        "unavailable_context": unavailable_context,
        "llm": llm,
        "narrative": narrative,
    }


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
