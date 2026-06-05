from dataclasses import dataclass
from os import getenv


@dataclass(frozen=True)
class Settings:
    app_env: str = "local"
    log_level: str = "info"
    database_url: str = "postgresql://signaldesk:signaldesk@localhost:5432/signaldesk"
    redis_url: str = "redis://localhost:6379/0"
    llm_provider: str = "none"

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            app_env=getenv("APP_ENV", cls.app_env),
            log_level=getenv("LOG_LEVEL", cls.log_level),
            database_url=getenv("DATABASE_URL", cls.database_url),
            redis_url=getenv("REDIS_URL", cls.redis_url),
            llm_provider=getenv("LLM_PROVIDER", cls.llm_provider),
        )
