from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, read from environment variables (prefix MC_) or a .env file."""

    model_config = SettingsConfigDict(env_prefix="MC_", env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://mc:mc@localhost:5433/mission_control"
    test_database_url: str = "postgresql+psycopg://mc:mc@localhost:5433/mission_control_test"
    jwt_secret: str = "dev-only-secret-change-me-in-production-0123456789"
    token_ttl_minutes: int = 8 * 60


@lru_cache
def get_settings() -> Settings:
    return Settings()
