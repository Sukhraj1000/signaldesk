import json
from pathlib import Path

import pytest
from signaldesk_backend import (
    assemble_ta_signal_card_report,
    extract_ta_signal_card,
    validate_ta_signal_card_report,
)


def _base_sections() -> dict[str, object]:
    unavailable_context = [
        {
            "context_type": "fundamentals",
            "reason": "not available in fixture",
            "provider": "fixture",
        }
    ]
    risk = {
        "flags": [{"kind": "scope", "severity": "info"}],
        "unavailable_context": unavailable_context,
    }
    score = {"breakdowns": [{"category": "data_quality", "score": "100", "reasons": []}]}
    return {
        "schema_version": "signaldesk.ta.v1",
        "identity": {
            "symbol": "AMD",
            "timeframe": "1d",
            "generated_at": "2024-01-01T00:00:00+00:00",
            "schema_version": "signaldesk.ta.v1",
        },
        "provider_mode": {"mode": "explicit", "price_provider": "fixture"},
        "facts": {"symbol": "AMD", "provider": "fixture", "interval": "1d"},
        "trend": {"regimes": {}},
        "levels": {"support": None, "resistance": None},
        "events": (),
        "risk": risk,
        "score": score,
        "provenance": [{"provider": "fixture", "source": "historical_candles"}],
        "unavailable_context": unavailable_context,
        "deterministic_signals": {"events": ()},
        "flat_fields": {"symbol": "AMD", "provider": "fixture"},
    }


def test_assemble_ta_signal_card_report_uses_single_canonical_card_object() -> None:
    sections = _base_sections()

    payload = assemble_ta_signal_card_report(**sections)  # type: ignore[arg-type]

    assert payload["schema_version"] == "signaldesk.ta.v1"
    assert payload["symbol"] == "AMD"
    assert payload["signal_card"]["identity"] is payload["identity"]
    assert payload["signal_card"]["provider_mode"] is payload["provider_mode"]
    assert payload["signal_card"]["facts"] is payload["facts"]
    assert payload["signal_card"]["trend"] is payload["trend"]
    assert payload["signal_card"]["levels"] is payload["levels"]
    assert payload["signal_card"]["events"] is payload["events"]
    assert payload["signal_card"]["risk"] is payload["risk"]
    assert payload["signal_card"]["score"] is payload["score"]
    assert payload["signal_card"]["provenance"] is payload["provenance"]
    assert payload["signal_card"]["unavailable_context"] is payload["unavailable_context"]
    assert payload["risks"] is payload["risk"]["flags"]
    assert payload["scores"] is payload["score"]["breakdowns"]


def test_assemble_ta_signal_card_report_rejects_missing_required_sections() -> None:
    sections = _base_sections()
    sections["risk"] = {"flags": []}

    with pytest.raises(ValueError, match="risk section"):
        assemble_ta_signal_card_report(**sections)  # type: ignore[arg-type]



def test_assemble_ta_signal_card_report_rejects_schema_version_drift() -> None:
    sections = _base_sections()
    sections["schema_version"] = "signaldesk.ta.v2"

    with pytest.raises(ValueError, match="schema_version"):
        assemble_ta_signal_card_report(**sections)  # type: ignore[arg-type]


def test_validate_ta_signal_card_report_rejects_alias_drift() -> None:
    sections = _base_sections()
    payload = assemble_ta_signal_card_report(**sections)  # type: ignore[arg-type]
    payload["signal_card"] = {**payload["signal_card"], "facts": {"symbol": "AMD"}}

    with pytest.raises(ValueError, match="facts"):
        validate_ta_signal_card_report(payload)



def test_validate_ta_signal_card_report_rejects_schema_identity_drift() -> None:
    sections = _base_sections()
    payload = assemble_ta_signal_card_report(**sections)  # type: ignore[arg-type]
    payload["schema_version"] = "signaldesk.ta.v2"

    with pytest.raises(ValueError, match="schema_version"):
        validate_ta_signal_card_report(payload)


def test_validate_ta_signal_card_report_rejects_identity_fact_drift() -> None:
    sections = _base_sections()
    payload = assemble_ta_signal_card_report(**sections)  # type: ignore[arg-type]
    payload["facts"] = {**payload["facts"], "symbol": "NVDA"}
    payload["signal_card"] = {**payload["signal_card"], "facts": payload["facts"]}

    with pytest.raises(ValueError, match=r"facts\.symbol"):
        validate_ta_signal_card_report(payload)


def test_validate_ta_signal_card_report_rejects_provider_fact_drift() -> None:
    sections = _base_sections()
    payload = assemble_ta_signal_card_report(**sections)  # type: ignore[arg-type]
    payload["provider_mode"] = {**payload["provider_mode"], "price_provider": "other"}
    payload["signal_card"] = {
        **payload["signal_card"],
        "provider_mode": payload["provider_mode"],
    }

    with pytest.raises(ValueError, match="price_provider"):
        validate_ta_signal_card_report(payload)

def test_validate_ta_signal_card_report_rejects_risk_unavailable_context_drift() -> None:
    sections = _base_sections()
    payload = assemble_ta_signal_card_report(**sections)  # type: ignore[arg-type]
    payload["risk"] = {
        **payload["risk"],
        "unavailable_context": [
            {
                "context_type": "catalysts",
                "reason": "not evaluated",
                "provider": None,
            }
        ],
    }
    payload["signal_card"] = {**payload["signal_card"], "risk": payload["risk"]}

    with pytest.raises(ValueError, match=r"risk\.unavailable_context"):
        validate_ta_signal_card_report(payload)


def test_validate_ta_signal_card_report_rejects_non_object_risk() -> None:
    sections = _base_sections()
    payload = assemble_ta_signal_card_report(**sections)  # type: ignore[arg-type]
    payload["risk"] = []
    payload["signal_card"] = {**payload["signal_card"], "risk": payload["risk"]}

    with pytest.raises(ValueError, match=r"signal_card\.risk"):
        validate_ta_signal_card_report(payload)


def test_validate_ta_signal_card_report_rejects_missing_card_sections() -> None:
    sections = _base_sections()
    payload = assemble_ta_signal_card_report(**sections)  # type: ignore[arg-type]
    payload["signal_card"] = {
        key: value for key, value in payload["signal_card"].items() if key != "risk"
    }

    with pytest.raises(ValueError, match="risk"):
        validate_ta_signal_card_report(payload)


def test_extract_ta_signal_card_validates_and_returns_renderer_object() -> None:
    sections = _base_sections()
    payload = assemble_ta_signal_card_report(**sections)  # type: ignore[arg-type]

    card = extract_ta_signal_card(payload)

    assert card is payload["signal_card"]
    assert card["facts"] is payload["facts"]
    assert card["risk"] is payload["risk"]


def test_extract_ta_signal_card_rejects_drift_before_rendering() -> None:
    sections = _base_sections()
    payload = assemble_ta_signal_card_report(**sections)  # type: ignore[arg-type]
    payload["signal_card"] = {**payload["signal_card"], "score": {"breakdowns": []}}

    with pytest.raises(ValueError, match="score"):
        extract_ta_signal_card(payload)


def test_schema_required_sections_match_canonical_card_contract() -> None:
    schema_path = (
        Path(__file__).resolve().parents[1] / "docs/schemas/signaldesk.ta.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    expected_sections = [
        "identity",
        "provider_mode",
        "facts",
        "trend",
        "levels",
        "events",
        "risk",
        "score",
        "provenance",
        "unavailable_context",
        "llm",
        "narrative",
    ]

    assert schema["required"] == ["schema_version", *expected_sections, "signal_card"]
    assert schema["properties"]["signal_card"]["required"] == expected_sections

    sections = _base_sections()
    payload = assemble_ta_signal_card_report(**sections)  # type: ignore[arg-type]

    assert [section for section in expected_sections if section not in payload] == []
    assert [section for section in expected_sections if section not in payload["signal_card"]] == []
    assert all(payload["signal_card"][section] == payload[section] for section in expected_sections)

def test_schema_defines_enhanced_context_as_separate_provider_sourced_facts() -> None:
    schema_path = (
        Path(__file__).resolve().parents[1] / "docs/schemas/signaldesk.ta.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    fact_properties = schema["$defs"]["facts"]["properties"]
    fundamental_context = schema["$defs"]["fundamental_context"]
    catalyst_context = schema["$defs"]["catalyst_context"]
    catalyst_event = schema["$defs"]["catalyst_event"]

    assert fact_properties["fundamentals"] == {"$ref": "#/$defs/fundamental_context"}
    assert fact_properties["catalysts"] == {"$ref": "#/$defs/catalyst_context"}
    assert fundamental_context["additionalProperties"] is False
    assert catalyst_context["additionalProperties"] is False
    assert catalyst_event["additionalProperties"] is False
    assert fundamental_context["required"] == [
        "symbol",
        "provider",
        "generated_at",
        "company_name",
        "exchange",
        "industry",
        "sector",
        "market_cap",
        "currency",
        "price",
        "beta",
        "pe_ratio",
        "eps",
        "source_url",
    ]
    assert catalyst_context["required"] == ["symbol", "provider", "generated_at", "events"]
    assert catalyst_event["required"] == [
        "headline",
        "provider",
        "published_at",
        "source",
        "url",
        "summary",
    ]


def test_schema_keeps_enhanced_context_out_of_deterministic_sections() -> None:
    schema_path = (
        Path(__file__).resolve().parents[1] / "docs/schemas/signaldesk.ta.v1.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    for section_name in ("trend", "levels", "risk", "score"):
        section_schema = schema["$defs"][section_name]
        assert "fundamentals" not in section_schema.get("properties", {})
        assert "catalysts" not in section_schema.get("properties", {})

    provider_mode = schema["$defs"]["provider_mode"]
    assert provider_mode["properties"]["fundamentals_provider"] == {
        "type": ["string", "null"]
    }
    assert provider_mode["properties"]["catalyst_provider"] == {"type": ["string", "null"]}

