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
