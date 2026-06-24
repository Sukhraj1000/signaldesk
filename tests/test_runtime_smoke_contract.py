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
