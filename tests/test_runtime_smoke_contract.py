import json
from pathlib import Path


def test_tox_smoke_covers_guarded_llm_runtime_entrypoints() -> None:
    tox_ini = Path("tox.ini").read_text(encoding="utf-8")

    assert "signaldesk llm prompt-payload AMD --provider local-fixture --output json" in tox_ini
    assert "signaldesk llm chat-messages AMD --provider local-fixture --output json" in tox_ini
    assert "signaldesk llm validate-output fixtures/llm/valid-explanation.json" in tox_ini


def test_llm_validate_output_smoke_fixture_is_schema_valid() -> None:
    from signaldesk_backend import (
        LLM_EXPLANATION_OUTPUT_SCHEMA_VERSION,
        validate_llm_explanation_output,
    )

    fixture = json.loads(
        Path("fixtures/llm/valid-explanation.json").read_text(encoding="utf-8")
    )

    assert (
        validate_llm_explanation_output(fixture)["schema_version"]
        == LLM_EXPLANATION_OUTPUT_SCHEMA_VERSION
    )


def test_tox_smoke_covers_web_provider_status_entrypoint() -> None:
    tox_ini = Path("tox.ini").read_text(encoding="utf-8")

    assert "signaldesk web provider-status --mode default --output json" in tox_ini


def test_tox_smoke_covers_api_openapi_entrypoint() -> None:
    tox_ini = Path("tox.ini").read_text(encoding="utf-8")

    assert "signaldesk-api openapi" in tox_ini


def test_tox_smoke_covers_web_watchlist_scan_entrypoint() -> None:
    tox_ini = Path("tox.ini").read_text(encoding="utf-8")

    assert (
        "signaldesk web watchlist-scan --watchlist watchlists/default.yaml "
        "--provider local-fixture --llm none --output json"
        in tox_ini
    )


def test_persistence_caching_scheduling_docs_define_cache_invalidation_policy() -> None:
    docs = Path("docs/persistence-caching-scheduling.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "docs/persistence-caching-scheduling.md" in readme
    assert "## Provider-response cache invalidation" in docs
    assert "Cache keys should include at least:" in docs
    assert "provider name and provider role" in docs
    assert "symbol or watchlist member identity" in docs
    assert "interval and requested date range for candles" in docs
    assert "provider mode" in docs
    assert "request shape that changes provider output" in docs
    assert "adapter schema version" in docs
    assert "delete the entire local provider-cache namespace" in docs
    assert "A cached failure must still render as `Unavailable context`" in docs
    assert "not a report artifact cache key" in docs

