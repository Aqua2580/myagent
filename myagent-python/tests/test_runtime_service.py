from __future__ import annotations

from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from fakeredis.aioredis import FakeRedis
from pydantic import SecretStr
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncEngine

from myagent.config import Settings
from myagent.domain import AgentStatus
from myagent.persistence import (
    Base,
    CheckpointConflictError,
    Checkpointer,
    CheckpointOwnershipError,
    RedisCheckpointCache,
    SqlCheckpointStore,
    create_database_engine,
    create_session_factory,
)
from myagent.runtime import (
    EngineKind,
    InvalidRunTransitionError,
    RunAlreadyActiveError,
    RunEngineMismatchError,
    RunService,
    RunSession,
    RuntimeRepository,
    StartRunCommand,
    ThreadAccessDeniedError,
    ThreadNotFoundError,
)


async def build_service(
    database_path: Path,
) -> tuple[RunService, Checkpointer, AsyncEngine, FakeRedis]:
    settings = Settings(
        _env_file=None,
        database_url=SecretStr(f"sqlite+aiosqlite:///{database_path.as_posix()}"),
    )
    engine = create_database_engine(settings)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = create_session_factory(engine)
    store = SqlCheckpointStore(session_factory)
    fake_redis = FakeRedis(decode_responses=True)
    cache = RedisCheckpointCache(
        cast(Redis, fake_redis),
        key_prefix="test:runtime:v1",
        ttl_seconds=600,
    )
    checkpointer = Checkpointer(store, cache)
    repository = RuntimeRepository(session_factory, store)
    return RunService(repository, checkpointer), checkpointer, engine, fake_redis


async def close_runtime(engine: AsyncEngine, fake_redis: FakeRedis) -> None:
    await fake_redis.aclose()
    await engine.dispose()


@pytest.mark.asyncio
async def test_run_lifecycle_is_atomic_resumable_and_engine_is_fixed(tmp_path: Path) -> None:
    service, checkpointer, engine, fake_redis = await build_service(tmp_path / "lifecycle.db")
    try:
        started = await service.start_run(
            StartRunCommand(
                user_id="user-1",
                engine=EngineKind.LANGGRAPH,
                input_message="Research the incident",
                request_payload={"depth": "deep"},
            )
        )

        assert started.engine is EngineKind.LANGGRAPH
        assert started.checkpoint_version == 1
        assert started.state.status is AgentStatus.RUNNING
        assert started.state.messages[-1].content == "Research the incident"

        started.state.increment_step_count()
        started.state.status = AgentStatus.WAITING_CONFIRMATION
        waiting = await service.save_progress(started)
        resumed = await service.resume_run(waiting.run_id, user_id="user-1")

        assert waiting.checkpoint_version == 2
        assert resumed.engine is EngineKind.LANGGRAPH
        assert resumed.state.status is AgentStatus.WAITING_CONFIRMATION
        assert resumed.state.run_step_count == 1

        completed = await service.complete_run(
            resumed,
            result_payload={"answer": "contained"},
        )
        durable = await checkpointer.load_durable(completed.state.thread_id)

        assert completed.checkpoint_version == 3
        assert completed.state.status is AgentStatus.COMPLETED
        assert durable is not None
        assert durable == await checkpointer.load_hot(completed.state.thread_id)
        with pytest.raises(InvalidRunTransitionError, match="terminal"):
            await service.resume_run(completed.run_id, user_id="user-1")
    finally:
        await close_runtime(engine, fake_redis)


@pytest.mark.asyncio
async def test_second_active_run_is_rejected_then_allowed_after_cancel(tmp_path: Path) -> None:
    service, checkpointer, engine, fake_redis = await build_service(tmp_path / "active.db")
    try:
        first = await service.start_run(
            StartRunCommand(
                user_id="user-2",
                engine=EngineKind.NATIVE,
                input_message="First request",
            )
        )
        with pytest.raises(RunAlreadyActiveError, match="active run"):
            await service.start_run(
                StartRunCommand(
                    user_id="user-2",
                    engine=EngineKind.LANGGRAPH,
                    input_message="Conflicting request",
                    thread_id=first.state.thread_id,
                )
            )

        unchanged = await checkpointer.load_durable(first.state.thread_id)
        assert unchanged is not None
        assert unchanged.version == 1
        assert unchanged.state.messages[-1].content == "First request"

        cancelled = await service.cancel_run(first)
        second = await service.start_run(
            StartRunCommand(
                user_id="user-2",
                engine=EngineKind.LANGGRAPH,
                input_message="Next request",
                thread_id=cancelled.state.thread_id,
            )
        )
        assert second.engine is EngineKind.LANGGRAPH
        assert second.checkpoint_version == 3
        assert second.state.messages[-1].content == "Next request"
    finally:
        await close_runtime(engine, fake_redis)


@pytest.mark.asyncio
async def test_run_context_cannot_switch_engine_or_reuse_stale_version(tmp_path: Path) -> None:
    service, checkpointer, engine, fake_redis = await build_service(tmp_path / "guards.db")
    try:
        started = await service.start_run(
            StartRunCommand(
                user_id="user-3",
                engine=EngineKind.NATIVE,
                input_message="Guard this run",
            )
        )
        forged = RunSession(
            run_id=started.run_id,
            engine=EngineKind.LANGGRAPH,
            checkpoint_version=started.checkpoint_version,
            state=started.state.model_copy(deep=True),
            started_at=started.started_at,
        )
        with pytest.raises(RunEngineMismatchError, match="immutable"):
            await service.save_progress(forged)

        started.state.increment_step_count()
        progressed = await service.save_progress(started)
        with pytest.raises(CheckpointConflictError, match="expected checkpoint version"):
            await service.save_progress(started)

        durable = await checkpointer.load_durable(progressed.state.thread_id)
        assert durable is not None
        assert durable.version == 2
        assert durable.state.total_step_count == 1
    finally:
        await close_runtime(engine, fake_redis)


@pytest.mark.asyncio
async def test_thread_ownership_is_enforced_on_start_resume_and_checkpoint(tmp_path: Path) -> None:
    service, checkpointer, engine, fake_redis = await build_service(tmp_path / "ownership.db")
    try:
        started = await service.start_run(
            StartRunCommand(
                user_id="owner",
                engine=EngineKind.NATIVE,
                input_message="Private request",
            )
        )
        with pytest.raises(ThreadAccessDeniedError, match="another user"):
            await service.resume_run(started.run_id, user_id="intruder")

        started.state.user_id = "intruder"
        with pytest.raises(CheckpointOwnershipError, match="owner"):
            await service.save_progress(started)

        missing_thread = uuid4()
        with pytest.raises(ThreadNotFoundError, match=str(missing_thread)):
            await service.start_run(
                StartRunCommand(
                    user_id="owner",
                    engine=EngineKind.NATIVE,
                    input_message="Missing",
                    thread_id=missing_thread,
                )
            )

        durable = await checkpointer.load_durable(started.state.thread_id)
        assert durable is not None
        assert durable.state.user_id == "owner"
    finally:
        await close_runtime(engine, fake_redis)


@pytest.mark.asyncio
async def test_terminal_methods_validate_inputs_and_prevent_second_finish(tmp_path: Path) -> None:
    service, _, engine, fake_redis = await build_service(tmp_path / "terminal.db")
    try:
        started = await service.start_run(
            StartRunCommand(
                user_id="user-4",
                engine=EngineKind.NATIVE,
                input_message="Finish once",
            )
        )
        with pytest.raises(ValueError, match="blank"):
            await service.fail_run(started, error_message="   ")

        failed = await service.fail_run(started, error_message="safe failure summary")
        assert failed.state.status is AgentStatus.ERROR
        with pytest.raises(InvalidRunTransitionError, match="terminal"):
            await service.cancel_run(failed)
    finally:
        await close_runtime(engine, fake_redis)
