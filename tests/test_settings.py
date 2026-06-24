from pytest import MonkeyPatch
from signaldesk_backend import Settings


def test_settings_load_defaults(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("LLM_API_KEY", raising=False)

    settings = Settings.from_env()

    assert settings.app_env == "local"
    assert settings.llm_provider == "none"
    assert settings.llm_model == "openai/gpt-4o-mini"
    assert settings.llm_endpoint_url == "https://openrouter.ai/api/v1/chat/completions"
    assert settings.llm_api_key_configured is False


def test_settings_reports_llm_adapter_configuration_without_secret(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("LLM_MODEL", "openrouter/test-model")
    monkeypatch.setenv("LLM_ENDPOINT_URL", "https://openrouter.example.test/api/v1/chat/completions")
    monkeypatch.setenv("LLM_API_KEY", "unit-test-secret")

    settings = Settings.from_env()

    assert settings.llm_provider == "openrouter"
    assert settings.llm_model == "openrouter/test-model"
    assert settings.llm_endpoint_url == "https://openrouter.example.test/api/v1/chat/completions"
    assert settings.llm_api_key_configured is True
    assert "unit-test-secret" not in repr(settings)
