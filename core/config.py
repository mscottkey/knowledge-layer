import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    NEO4J_URI: str = ""
    NEO4J_USERNAME: str = ""
    NEO4J_PASSWORD: str = ""

    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    DATABASE_URL: str = ""

    OPENAI_API_KEY: str = ""
    REDIS_URL: str = "redis://localhost:6379"

    CONFIDENCE_THRESHOLD: float = 0.80
    EMBEDDING_MODEL: str = "text-embedding-3-large"
    SYNTHESIS_MODEL: str = "gpt-4o"

    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"

    USE_MOCKS: bool = False

    @property
    def use_mocks(self) -> bool:
        return self.USE_MOCKS or os.getenv("USE_MOCKS", "").lower() == "true"


@lru_cache
def get_settings() -> Settings:
    return Settings()
