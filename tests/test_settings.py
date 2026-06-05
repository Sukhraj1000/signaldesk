from signaldesk_backend import Settings


def test_settings_load_defaults() -> None:
    settings = Settings.from_env()

    assert settings.app_env == "local"
    assert settings.llm_provider == "none"
