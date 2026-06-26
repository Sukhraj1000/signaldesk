
from signaldesk_backend import (
    CHART_OVERLAY_PRESENTATION_SCHEMA_VERSION,
    PRESENTATION_SCHEMA_VERSION,
    PROVIDER_STATUS_PRESENTATION_SCHEMA_VERSION,
    WATCHLIST_SCAN_PRESENTATION_SCHEMA_VERSION,
    assemble_ta_signal_card_report,
    build_chart_overlay_presentation,
    build_provider_status_presentation,
    build_signal_card_presentation,
    build_watchlist_scan_presentation,
    extract_ta_signal_card,
)


def _fixture_ta_report() -> dict[str, object]:
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
    return report


def _fixture_signal_card() -> dict[str, object]:
    return extract_ta_signal_card(_fixture_ta_report())


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


def test_dashboard_presentation_rejects_full_ta_report_shape() -> None:
    report = _fixture_ta_report()
    report["facts"] = {"symbol": "REPORT", "provider": "report-provider"}

    try:
        build_signal_card_presentation(report)
    except ValueError as exc:
        assert "nested signal_card" in str(exc)
    else:
        raise AssertionError("full TA report should fail before presentation rendering")


def test_dashboard_presentation_accepts_extracted_signal_card_contract() -> None:
    report = _fixture_ta_report()

    presentation = build_signal_card_presentation(extract_ta_signal_card(report))

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



def test_provider_status_presentation_groups_provider_facts_without_live_checks() -> None:
    presentation = build_provider_status_presentation(
        provider_mode={
            "mode": "default",
            "price_provider": "yfinance",
            "fundamentals_provider": None,
            "catalyst_provider": None,
            "llm_provider": None,
            "unavailable_context": [
                {
                    "context_type": "fundamentals",
                    "reason": "not configured in default mode",
                    "provider": None,
                    "details": {},
                }
            ],
        },
        provider_capabilities=(
            {
                "provider": "yfinance",
                "tier": "default",
                "role": "price",
                "realtime": False,
                "historical": True,
                "asset_classes": ["equity"],
                "intervals": ["1d"],
                "credential_state": "not_required",
                "live_check": False,
                "max_history_days": 365,
                "rate_limit_per_minute": None,
            },
            {
                "provider": "fmp",
                "tier": "enhanced",
                "role": "fundamentals",
                "realtime": False,
                "historical": False,
                "asset_classes": ["equity"],
                "intervals": [],
                "credential_state": "not_configured",
                "live_check": False,
                "max_history_days": None,
                "rate_limit_per_minute": None,
            },
        ),
    )

    assert presentation["schema_version"] == PROVIDER_STATUS_PRESENTATION_SCHEMA_VERSION
    assert presentation["mode_summary"] == {
        "mode": "default",
        "price_provider": "yfinance",
        "fundamentals_provider": None,
        "catalyst_provider": None,
        "llm_provider": None,
    }
    assert [row["provider"] for row in presentation["provider_rows"]] == ["yfinance", "fmp"]
    assert {section["label"] for section in presentation["credential_sections"]} == {
        "not_configured",
        "not_required",
    }
    assert {section["label"] for section in presentation["role_sections"]} == {
        "fundamentals",
        "price",
    }
    assert presentation["unavailable_context"][0]["context_type"] == "fundamentals"


def test_provider_status_presentation_rejects_missing_mode_fields() -> None:
    try:
        build_provider_status_presentation(provider_mode={}, provider_capabilities=())
    except ValueError as exc:
        assert "mode" in str(exc)
    else:
        raise AssertionError("missing provider mode fields should fail")


def test_fixture_signal_card_builds_chart_overlay_presentation_model() -> None:
    presentation = build_chart_overlay_presentation(_fixture_signal_card())

    assert presentation["schema_version"] == CHART_OVERLAY_PRESENTATION_SCHEMA_VERSION
    assert presentation["chart"] == {
        "symbol": "AMD",
        "timeframe": "1d",
        "generated_at": "2024-01-01T00:00:00+00:00",
        "price_provider": "local-fixture",
    }
    assert [level["role"] for level in presentation["horizontal_levels"]] == [
        "support",
        "resistance",
        "fibonacci",
        "confirmation",
        "invalidation",
    ]
    assert presentation["horizontal_levels"][3]["emphasis"] is True
    assert presentation["horizontal_levels"][4]["emphasis"] is True
    assert presentation["event_markers"][0]["label"] == "breakout"
    assert {badge["label"] for badge in presentation["trend_badges"]} == {"price"}
    assert presentation["risk_markers"][0]["severity"] == "info"
    assert {row["context_type"] for row in presentation["unavailable_context"]} == {
        "fundamentals",
        "catalyst",
    }
    assert presentation["rendering_contract"]["no_dashboard_analysis"] is True


def test_chart_overlay_presentation_rejects_full_ta_report_shape() -> None:
    try:
        build_chart_overlay_presentation(_fixture_ta_report())
    except ValueError as exc:
        assert "nested signal_card" in str(exc)
    else:
        raise AssertionError("full TA report should fail before chart overlay rendering")


def test_chart_overlay_presentation_rejects_non_mapping_events() -> None:
    signal_card = _fixture_signal_card()
    signal_card["events"] = ["not-an-event"]

    try:
        build_chart_overlay_presentation(signal_card)
    except ValueError as exc:
        assert "entries must be JSON objects" in str(exc)
    else:
        raise AssertionError("non-object event markers should fail")


def test_watchlist_scan_presentation_groups_canonical_report_rows() -> None:
    payload = {
        "schema_version": "signaldesk.watchlist_report.v1",
        "report_type": "watchlist",
        "generated_at": "2024-01-01T00:00:00+00:00",
        "watchlist": "watchlists/default.yaml",
        "watchlist_model": {
            "name": "Default TA Watchlist",
            "tags": ["default-mode"],
            "asset_class": "equity",
            "enabled": True,
            "symbols": ["AMD", "MSFT"],
        },
        "provider_mode": {
            "mode": "explicit",
            "price_provider": "local-fixture",
            "unavailable_context": [
                {"context_type": "fundamentals", "reason": "not configured"}
            ],
        },
        "symbols": ["AMD", "MSFT"],
        "ranked_setups": [
            {
                "symbol": "AMD",
                "status": "ok",
                "rank": 1,
                "summary": {
                    "symbol": "AMD",
                    "provider": "local-fixture",
                    "latest_close": "100.00",
                    "trend_regime": "uptrend",
                    "setup_quality_score": "70",
                    "risk_score": "40",
                    "levels": {
                        "confirmation": [{"kind": "breakout", "price": "101.00"}],
                        "invalidation": [{"kind": "stop", "price": "90.00"}],
                    },
                    "unavailable_context": [
                        {"context_type": "catalyst", "reason": "not configured"}
                    ],
                },
            }
        ],
        "failed_symbols": [
            {"symbol": "MSFT", "status": "error", "error": "provider unavailable"}
        ],
        "skipped_symbols": [],
        "summary": {"total": 2, "ok": 1, "failed": 1, "skipped": 0},
        "provenance": [{"provider": "local-fixture", "source": "historical_candles"}],
    }

    presentation = build_watchlist_scan_presentation(payload)

    assert presentation["schema_version"] == WATCHLIST_SCAN_PRESENTATION_SCHEMA_VERSION
    assert presentation["headline"]["name"] == "Default TA Watchlist"
    assert presentation["provider_badge"] == {
        "mode": "explicit",
        "price_provider": "local-fixture",
    }
    assert presentation["summary_tiles"] == {
        "total": 2,
        "ok": 1,
        "failed": 1,
        "skipped": 0,
    }
    assert presentation["ranked_setup_rows"][0]["symbol"] == "AMD"
    assert presentation["ranked_setup_rows"][0]["confirmation"][0]["kind"] == "breakout"
    assert (
        presentation["ranked_setup_rows"][0]["unavailable_context"][0]["context_type"]
        == "catalyst"
    )
    assert presentation["failed_rows"][0]["reason"] == "provider unavailable"
    assert presentation["provider_unavailable_context"][0]["context_type"] == "fundamentals"
    assert presentation["rendering_contract"]["no_dashboard_analysis"] is True


def test_watchlist_scan_presentation_rejects_non_mapping_ranked_rows() -> None:
    payload = {
        "watchlist": "watchlists/default.yaml",
        "watchlist_model": {"name": "Default TA Watchlist"},
        "generated_at": "2024-01-01T00:00:00+00:00",
        "provider_mode": {"mode": "explicit", "price_provider": "local-fixture"},
        "symbols": ["AMD"],
        "ranked_setups": ["AMD"],
        "failed_symbols": [],
        "skipped_symbols": [],
        "summary": {"total": 1, "ok": 1, "failed": 0, "skipped": 0},
        "provenance": [],
    }

    try:
        build_watchlist_scan_presentation(payload)
    except ValueError as exc:
        assert "entries must be JSON objects" in str(exc)
    else:
        raise AssertionError("non-object ranked rows should fail")


def test_watchlist_scan_presentation_rejects_string_symbols() -> None:
    payload = {
        "watchlist": "watchlists/default.yaml",
        "watchlist_model": {"name": "Default TA Watchlist"},
        "generated_at": "2024-01-01T00:00:00+00:00",
        "provider_mode": {"mode": "explicit", "price_provider": "local-fixture"},
        "symbols": "AMD",
        "ranked_setups": [],
        "failed_symbols": [],
        "skipped_symbols": [],
        "summary": {"total": 1, "ok": 0, "failed": 0, "skipped": 0},
        "provenance": [],
    }

    try:
        build_watchlist_scan_presentation(payload)
    except ValueError as exc:
        assert "symbols section must be a list" in str(exc)
    else:
        raise AssertionError("string symbols should fail before presentation rendering")
