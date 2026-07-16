"""Application configuration loaded from environment variables."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings with safe, non-secret development defaults."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="MYAGENT_",
        extra="ignore",
    )

    app_name: str = "MyAgent Python"
    environment: Literal["development", "test", "production"] = "development"
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: SecretStr = SecretStr("postgresql+asyncpg://localhost:5432/myagent")
    database_echo: bool = False
    database_pool_size: int = Field(default=10, ge=1)
    database_max_overflow: int = Field(default=20, ge=0)
    redis_url: SecretStr = SecretStr("redis://localhost:6379/0")
    checkpoint_key_prefix: str = Field(default="myagent:checkpoint:v1", min_length=1)
    checkpoint_ttl_seconds: int = Field(default=86_400, ge=60)


@lru_cache
def get_settings() -> Settings:
    """Return a process-wide immutable configuration snapshot."""

    return Settings()

