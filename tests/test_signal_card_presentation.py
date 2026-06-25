
from signaldesk_backend import (
    PRESENTATION_SCHEMA_VERSION,
    assemble_ta_signal_card_report,
    build_signal_card_presentation,
    extract_ta_signal_card,
)


def _fixture_signal_card() -> dict[str, object]:
    unavailable_context = [
        {
            "context_type": "fundamentals",
            "reason": "not available in fixture",
            "provider": "fixture",
        },
        {
            "context_type": "catalyst",
            "reason": "not configured for default fixture smoke",
            "provider": "fixture",
        },
    ]
    report = assemble_ta_signal_card_report(
        schema_version="signaldesk.ta.v1",
        identity={
            "symbol": "AMD",
            "timeframe": "1d",
            "generated_at": "2024-01-01T00:00:00+00:00",
            "schema_version": "signaldesk.ta.v1",
        },
        provider_mode={"mode": "explicit", "price_provider": "local-fixture"},
        facts={"symbol": "AMD", "provider": "local-fixture", "interval": "1d"},
        trend={"regimes": {"price": "uptrend"}},
        levels={
            "support": [{"kind": "support", "price": "100.00"}],
            "resistance": [{"kind": "resistance", "price": "120.00"}],
            "fibonacci": [{"kind": "fib_0_618", "price": "108.00"}],
            "confirmation": [{"kind": "breakout_confirmation", "price": "121.00"}],
            "invalidation": [{"kind": "setup_invalidation", "price": "99.00"}],
        },
        events=({"kind": "breakout", "status": "confirmed"},),
        risk={
            "flags": [{"kind": "missing_context", "severity": "info"}],
            "unavailable_context": unavailable_context,
        },
        score={
            "breakdowns": [
                {"category": "setup_quality", "score": "70", "reasons": []},
                {"category": "risk", "score": "40", "reasons": []},
            ]
        },
        provenance=[{"provider": "local-fixture", "source": "historical_candles"}],
        unavailable_context=unavailable_context,
        deterministic_signals={"events": ({"kind": "breakout"},)},
        flat_fields={"symbol": "AMD", "provider": "local-fixture"},
    )
    return extract_ta_signal_card(report)


def test_fixture_signal_card_builds_dashboard_presentation_model() -> None:
    signal_card = _fixture_signal_card()

    presentation = build_signal_card_presentation(signal_card)

    assert presentation["schema_version"] == PRESENTATION_SCHEMA_VERSION
    assert presentation["headline"] == {
        "symbol": "AMD",
        "timeframe": "1d",
        "generated_at": "2024-01-01T00:00:00+00:00",
        "llm": "none",
    }
    assert presentation["provider_badge"] == {
        "mode": "explicit",
        "price_provider": "local-fixture",
    }
    assert presentation["level_groups"]["support"][0]["label"] == "support"
    assert presentation["level_groups"]["confirmation"][0]["label"] == "breakout_confirmation"
    assert presentation["level_groups"]["invalidation"][0]["label"] == "setup_invalidation"
    assert presentation["event_rows"][0]["label"] == "breakout"
    assert presentation["risk_panel"]["flags"][0]["label"] == "missing_context"
    assert {
        row["label"] for row in presentation["risk_panel"]["unavailable_context"]
    } == {"fundamentals", "catalyst"}
    assert [row["label"] for row in presentation["score_rows"]] == ["setup_quality", "risk"]
    assert presentation["provenance_rows"][0]["label"] == "local-fixture"


def test_dashboard_presentation_accepts_only_nested_signal_card_contract() -> None:
    signal_card = _fixture_signal_card()
    signal_card["facts"] = {"symbol": "NESTED", "provider": "nested-provider"}

    presentation = build_signal_card_presentation(signal_card)

    assert presentation["headline"]["symbol"] == "AMD"
    assert presentation["provider_badge"]["price_provider"] == "local-fixture"


def test_dashboard_presentation_rejects_missing_canonical_sections() -> None:
    signal_card = _fixture_signal_card()
    del signal_card["risk"]

    try:
        build_signal_card_presentation(signal_card)
    except ValueError as exc:
        assert "risk" in str(exc)
    else:
        raise AssertionError("missing risk section should fail")
