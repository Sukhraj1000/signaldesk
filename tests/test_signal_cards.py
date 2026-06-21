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
