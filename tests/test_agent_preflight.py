from importlib import util
from pathlib import Path
from types import ModuleType


def _load_agent_preflight() -> ModuleType:
    spec = util.spec_from_file_location("agent_preflight", Path("scripts/agent_preflight.py"))
    assert spec is not None
    assert spec.loader is not None
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sensitive_secret_path_detection_blocks_dotenv_and_private_keys() -> None:
    preflight = _load_agent_preflight()

    assert preflight.is_sensitive_secret_path(".env") is True
    assert preflight.is_sensitive_secret_path(".env.local") is True
    assert preflight.is_sensitive_secret_path("config/prod.env") is True
    assert preflight.is_sensitive_secret_path(".envrc") is True
    assert preflight.is_sensitive_secret_path(".netrc") is True
    assert preflight.is_sensitive_secret_path(".npmrc") is True
    assert preflight.is_sensitive_secret_path(".pypirc") is True
    assert preflight.is_sensitive_secret_path("pip.conf") is True
    assert preflight.is_sensitive_secret_path("config/prod.env.pem") is True
    assert preflight.is_sensitive_secret_path("keys/id_ed25519") is True
    assert preflight.is_sensitive_secret_path("certs/provider.p12") is True


def test_sensitive_secret_path_detection_allows_documented_templates() -> None:
    preflight = _load_agent_preflight()

    assert preflight.is_sensitive_secret_path(".env.example") is False
    assert preflight.is_sensitive_secret_path("docs/.env.sample") is False
    assert preflight.is_sensitive_secret_path("config/.env.template") is False
    assert preflight.is_sensitive_secret_path("docs/public-key-example.txt") is False


def test_secret_value_detection_catches_modern_provider_tokens() -> None:
    preflight = _load_agent_preflight()

    obvious_secrets = [
        "github_pat_" + "A" * 82,
        "glpat-" + "A" * 20,
        "xoxb-" + "123456789012" + "-" + "123456789012" + "-" + "a" * 24,
        "sk-proj-" + "A" * 40,
        "sk-or-v1-" + "a" * 64,
    ]

    for value in obvious_secrets:
        assert preflight.SECRET_VALUE_RE.search(value) is not None


def test_secret_value_detection_ignores_documentation_placeholders() -> None:
    preflight = _load_agent_preflight()

    placeholders = [
        "github_pat_<redacted>",
        "glpat-example-token",
        "sk-pro...E_ME",
        "sk-or-...E_ME",
    ]

    for value in placeholders:
        assert preflight.SECRET_VALUE_RE.search(value) is None
