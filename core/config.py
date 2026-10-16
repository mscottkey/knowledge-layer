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
    GEMINI_API_KEY: str = ""
    REDIS_URL: str = "redis://localhost:6379"

    CONFIDENCE_THRESHOLD: float = 0.80
    EMBEDDING_MODEL: str = "text-embedding-004"
    EMBEDDING_DIMENSION: int = 768
    SYNTHESIS_MODEL: str = "gemini-2.5-flash"

    LOG_LEVEL: str = "INFO"
    ENVIRONMENT: str = "development"

    # USE_MOCKS=true mocks everything. MOCK_STORES and MOCK_MODELS mock one side only,
    # for example real Neo4j and Postgres with fake embeddings and synthesis.
    USE_MOCKS: bool = False
    MOCK_STORES: bool = False
    MOCK_MODELS: bool = False

    @staticmethod
    def _env_flag(name: str) -> bool:
        return os.getenv(name, "").lower() == "true"

    @property
    def use_mocks(self) -> bool:
        return self.USE_MOCKS or self._env_flag("USE_MOCKS")

    @property
    def mock_stores(self) -> bool:
        """Neo4j, pgvector, Supabase and Redis are replaced by in-memory fakes."""
        return self.use_mocks or self.MOCK_STORES or self._env_flag("MOCK_STORES")

    @property
    def mock_models(self) -> bool:
        """Embeddings, synthesis and spaCy are replaced by deterministic local stand-ins."""
        return self.use_mocks or self.MOCK_MODELS or self._env_flag("MOCK_MODELS")


@lru_cache
def get_settings() -> Settings:
    return Settings()
