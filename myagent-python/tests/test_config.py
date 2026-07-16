from myagent.config import Settings, get_settings


def test_settings_use_safe_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.environment == "development"
    assert settings.port == 8000
    assert settings.log_level == "INFO"


def test_settings_are_cached() -> None:
    get_settings.cache_clear()

    assert get_settings() is get_settings()

