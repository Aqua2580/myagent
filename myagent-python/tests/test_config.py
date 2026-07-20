from myagent.config import Settings, get_settings


def test_settings_use_safe_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.port == 8000
    assert settings.log_level == "INFO"
    assert settings.database_url.get_secret_value().startswith("postgresql+asyncpg://")
    assert settings.redis_url.get_secret_value() == "redis://localhost:6379/0"
    assert settings.checkpoint_ttl_seconds == 86_400
    assert "localhost:5432" not in repr(settings)


def test_settings_are_cached() -> None:
    get_settings.cache_clear()

    assert get_settings() is get_settings()

