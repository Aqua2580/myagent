from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).parents[1]


def load_compose() -> dict[str, Any]:
    content = (PROJECT_ROOT / "compose.yaml").read_text(encoding="utf-8")
    parsed = yaml.safe_load(content)
    assert isinstance(parsed, dict)
    return parsed


def test_compose_uses_pinned_official_infrastructure_images() -> None:
    services = load_compose()["services"]

    assert services["postgres"]["image"] == "postgres:${POSTGRES_IMAGE_TAG:-18.4-alpine3.23}"
    assert services["redis"]["image"] == "redis:${REDIS_IMAGE_TAG:-8.8.0-alpine3.23}"
    assert set(services) == {"postgres", "redis"}


def test_compose_binds_ports_to_loopback_and_has_healthchecks() -> None:
    services = load_compose()["services"]

    assert services["postgres"]["ports"] == [
        "127.0.0.1:${POSTGRES_HOST_PORT:-5432}:5432"
    ]
    assert services["redis"]["ports"] == ["127.0.0.1:${REDIS_HOST_PORT:-6379}:6379"]
    assert services["postgres"]["healthcheck"]["retries"] == 12
    assert services["redis"]["healthcheck"]["retries"] == 12


def test_compose_uses_secret_files_and_named_volumes() -> None:
    compose = load_compose()
    postgres = compose["services"]["postgres"]
    redis = compose["services"]["redis"]

    assert postgres["environment"]["POSTGRES_PASSWORD_FILE"] == (
        "/run/secrets/postgres_password"
    )
    assert "POSTGRES_PASSWORD" not in postgres["environment"]
    assert redis["command"] == ["redis-server", "/run/secrets/redis_config"]
    assert compose["secrets"]["postgres_password"]["file"].endswith(
        "postgres_password.txt"
    )
    assert compose["secrets"]["redis_config"]["file"].endswith("redis.conf")
    assert postgres["volumes"] == ["postgres_data:/var/lib/postgresql"]
    assert redis["volumes"] == ["redis_data:/data"]


def test_redis_example_requires_auth_and_persists_data() -> None:
    config = (PROJECT_ROOT / "docker/secrets/redis.conf.example").read_text(
        encoding="utf-8"
    )

    assert "protected-mode yes" in config
    assert "requirepass replace-with" in config
    assert "appendonly yes" in config
    assert "appendfsync everysec" in config
    assert "maxmemory-policy allkeys-lru" in config


def test_real_docker_secrets_are_ignored() -> None:
    ignore_rules = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")

    assert "docker/secrets/postgres_password.txt" in ignore_rules
    assert "docker/secrets/redis.conf" in ignore_rules
    assert "docker/.env.app.generated" in ignore_rules


def test_setup_script_uses_cryptographic_randomness_and_avoids_secret_output() -> None:
    script = (PROJECT_ROOT / "scripts/setup_docker.ps1").read_text(encoding="utf-8")

    assert "RandomNumberGenerator" in script
    assert "ToHexString" in script
    assert "Refusing to overwrite existing local secret" in script
    assert 'Write-Host $postgresPassword' not in script
    assert 'Write-Host $redisPassword' not in script
