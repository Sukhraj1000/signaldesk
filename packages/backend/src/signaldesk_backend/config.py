from dataclasses import dataclass, field
from os import getenv


def _env_present(name: str) -> bool:
    value = getenv(name)
    return value is not None and bool(value.strip())


@dataclass(frozen=True)
class Settings:
    app_env: str = "local"
    log_level: str = "info"
    database_url: str = "postgresql://signaldesk:***@localhost:5432/signaldesk"
    redis_url: str = "redis://localhost:6379/0"
    llm_provider: str = "none"
    llm_model: str = "openai/gpt-4o-mini"
    llm_endpoint_url: str = field(
        default="https://openrouter.ai/api/v1/chat/completions", repr=False
    )
    llm_api_key_configured: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_env=getenv("APP_ENV", cls.app_env),
            log_level=getenv("LOG_LEVEL", cls.log_level),
            database_url=getenv("DATABASE_URL", cls.database_url),
            redis_url=getenv("REDIS_URL", cls.redis_url),
            llm_provider=getenv("LLM_PROVIDER", cls.llm_provider),
            llm_model=getenv("LLM_MODEL", cls.llm_model),
            llm_endpoint_url=getenv("LLM_ENDPOINT_URL", cls.llm_endpoint_url),
            llm_api_key_configured=_env_present("LLM_API_KEY"),
        )
