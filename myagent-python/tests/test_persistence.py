import asyncio
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from alembic.config import Config
from fakeredis.aioredis import FakeRedis
from pydantic import SecretStr, ValidationError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command
from myagent.config import Settings
from myagent.domain import ThreadState
from myagent.persistence import (
    Base,
    CheckpointConflictError,
    CheckpointEnvelope,
    Checkpointer,
    RedisCheckpointCache,
    SqlCheckpointStore,
    create_database_engine,
    create_session_factory,
)

PROJECT_ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
EXPECTED_TABLES = {"agent_threads", "agent_runs", "agent_checkpoints"}


def load_state() -> ThreadState:
    payload = json.loads(
        (FIXTURES / "thread_state_completed.json").read_text(encoding="utf-8")
    )
    return ThreadState.model_validate(payload)


def sqlite_settings(database_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=SecretStr(f"sqlite+aiosqlite:///{database_path.as_posix()}"),
    )


@pytest.mark.asyncio
async def test_sql_checkpoint_store_versions_round_trips_and_deletes(tmp_path: Path) -> None:
    database = create_database_engine(sqlite_settings(tmp_path / "checkpoints.db"))
    async with database.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    store = SqlCheckpointStore(create_session_factory(database))
    state = load_state()
    try:
        first = await store.save(state, expected_version=0)
        state.increment_step_count()
        second = await store.save(state, expected_version=1)
        restored = await store.load(state.thread_id)

        assert first.version == 1
        assert first.state.total_step_count == 1
        assert second.version == 2
        assert restored is not None
        assert restored.version == 2
        assert restored.state == state
        assert restored.saved_at.tzinfo is not None

        with pytest.raises(CheckpointConflictError, match="expected checkpoint version"):
            await store.save(state, expected_version=0)

        assert await store.delete(state.thread_id) is True
        assert await store.load(state.thread_id) is None
    finally:
        await database.dispose()


@pytest.mark.asyncio
async def test_redis_cache_keeps_newest_version_and_discards_invalid_data() -> None:
    fake_client = FakeRedis(decode_responses=True)
    cache = RedisCheckpointCache(
        cast(Redis, fake_client),
        key_prefix="test:checkpoint:v1",
        ttl_seconds=600,
    )
    state = load_state()
    newest = CheckpointEnvelope(version=3, state=state, saved_at=datetime.now(UTC))
    newer = CheckpointEnvelope(version=2, state=state, saved_at=datetime.now(UTC))
    older = CheckpointEnvelope(version=1, state=state, saved_at=datetime.now(UTC))

    assert await cache.put(newer) is True
    assert await cache.put(older) is False
    assert await cache.load(state.thread_id) == newer
    assert await fake_client.ttl(cache.key_for(state.thread_id)) > 0

    await fake_client.set(cache.key_for(state.thread_id), "not-json")
    assert await cache.put(newest) is True
    assert await cache.load(state.thread_id) == newest

    await fake_client.set(cache.key_for(state.thread_id), "not-json")
    assert await cache.load(state.thread_id) is None
    assert await fake_client.get(cache.key_for(state.thread_id)) is None
    await fake_client.aclose()


@pytest.mark.asyncio
async def test_checkpointer_falls_back_to_sql_and_rewarms_redis(tmp_path: Path) -> None:
    database = create_database_engine(sqlite_settings(tmp_path / "fallback.db"))
    async with database.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    fake_client = FakeRedis(decode_responses=True)
    cache = RedisCheckpointCache(
        cast(Redis, fake_client),
        key_prefix="test:checkpoint:v1",
        ttl_seconds=600,
    )
    checkpointer = Checkpointer(SqlCheckpointStore(create_session_factory(database)), cache)
    state = load_state()
    try:
        saved = await checkpointer.save(state, expected_version=0)
        await fake_client.flushall()

        loaded = await checkpointer.load_hot(state.thread_id)

        assert loaded == saved
        assert await cache.load(state.thread_id) == saved
        assert await checkpointer.load_durable(state.thread_id) == saved
    finally:
        await fake_client.aclose()
        await database.dispose()


@pytest.mark.asyncio
async def test_durable_save_succeeds_when_redis_refresh_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = create_database_engine(sqlite_settings(tmp_path / "redis-outage.db"))
    async with database.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    fake_client = FakeRedis(decode_responses=True)
    cache = RedisCheckpointCache(
        cast(Redis, fake_client),
        key_prefix="test:checkpoint:v1",
        ttl_seconds=600,
    )
    store = SqlCheckpointStore(create_session_factory(database))
    checkpointer = Checkpointer(store, cache)
    state = load_state()

    async def fail_cache_refresh(envelope: CheckpointEnvelope) -> bool:
        del envelope
        raise RedisError("simulated outage")

    monkeypatch.setattr(cache, "put", fail_cache_refresh)
    try:
        saved = await checkpointer.save(state, expected_version=0)

        assert await store.load(state.thread_id) == saved
    finally:
        await fake_client.aclose()
        await database.dispose()


def test_checkpoint_envelope_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        CheckpointEnvelope(version=1, state=load_state(), saved_at=datetime(2026, 7, 16))


def test_alembic_upgrade_and_downgrade_on_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "alembic.db"
    database_url = f"sqlite+aiosqlite:///{database_path.as_posix()}"
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    monkeypatch.delenv("MYAGENT_DATABASE_URL", raising=False)

    command.upgrade(config, "head")
    assert asyncio.run(read_table_names(database_url)) == EXPECTED_TABLES | {"alembic_version"}

    command.downgrade(config, "base")
    assert asyncio.run(read_table_names(database_url)) == {"alembic_version"}


def test_alembic_offline_sql_targets_postgresql_native_types() -> None:
    output = io.StringIO()
    config = Config(str(PROJECT_ROOT / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(PROJECT_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://localhost/myagent")

    command.upgrade(config, "head", sql=True)

    migration_sql = output.getvalue()
    assert "CREATE TABLE agent_threads" in migration_sql
    assert "JSONB" in migration_sql
    assert "UUID" in migration_sql


async def read_table_names(database_url: str) -> set[str]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            return await connection.run_sync(
                lambda sync_connection: set(inspect(sync_connection).get_table_names())
            )
    finally:
        await engine.dispose()
