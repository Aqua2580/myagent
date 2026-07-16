"""Transactional SQL repository for Run lifecycle and checkpoint coordination."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from pydantic import JsonValue
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from myagent.domain import AgentStatus, ThreadState
from myagent.persistence import (
    AsyncSessionFactory,
    CheckpointEnvelope,
    SqlCheckpointStore,
)
from myagent.persistence.models import RunRecord
from myagent.runtime.errors import (
    InvalidRunTransitionError,
    RunAlreadyActiveError,
    RunEngineMismatchError,
    RunNotFoundError,
    RunStateMismatchError,
)
from myagent.runtime.models import EngineKind

ACTIVE_STATUSES = frozenset({AgentStatus.RUNNING, AgentStatus.WAITING_CONFIRMATION})
TERMINAL_STATUSES = frozenset(
    {
        AgentStatus.COMPLETED,
        AgentStatus.PARTIAL_COMPLETED,
        AgentStatus.ERROR,
        AgentStatus.CANCELLED,
    }
)


@dataclass(frozen=True, slots=True)
class StoredRun:
    """Credential-free projection of a persisted Run record."""

    run_id: UUID
    thread_id: UUID
    engine: EngineKind
    status: AgentStatus
    started_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeCommit:
    """SQL-committed Run metadata and checkpoint awaiting cache publication."""

    run: StoredRun
    checkpoint: CheckpointEnvelope


class RuntimeRepository:
    """Keep Run metadata and its platform checkpoint in one SQL transaction."""

    def __init__(
        self,
        session_factory: AsyncSessionFactory,
        checkpoint_store: SqlCheckpointStore,
    ) -> None:
        self._session_factory = session_factory
        self._checkpoint_store = checkpoint_store

    async def start(
        self,
        state: ThreadState,
        *,
        engine: EngineKind,
        input_message: str,
        request_payload: dict[str, JsonValue],
        expected_version: int,
    ) -> RuntimeCommit:
        if state.status is not AgentStatus.RUNNING:
            raise InvalidRunTransitionError("a new run must start in running status")

        run_id = uuid4()
        started_at = datetime.now(UTC)
        try:
            async with self._session_factory() as session, session.begin():
                checkpoint = await self._checkpoint_store.append_in_transaction(
                    session,
                    state,
                    expected_version=expected_version,
                )
                active_run_id = await session.scalar(
                    select(RunRecord.run_id)
                    .where(
                        RunRecord.thread_id == state.thread_id,
                        RunRecord.status.in_(status.value for status in ACTIVE_STATUSES),
                    )
                    .limit(1)
                )
                if active_run_id is not None:
                    raise RunAlreadyActiveError("thread already has an active run")

                session.add(
                    RunRecord(
                        run_id=run_id,
                        thread_id=state.thread_id,
                        engine=engine.value,
                        status=state.status.value,
                        request_payload={
                            "input_message": input_message,
                            "parameters": request_payload,
                        },
                        started_at=started_at,
                    )
                )
                await session.flush()
        except IntegrityError as exc:
            raise RunAlreadyActiveError("thread run start conflicted with another writer") from exc

        return RuntimeCommit(
            run=StoredRun(
                run_id=run_id,
                thread_id=state.thread_id,
                engine=engine,
                status=AgentStatus.RUNNING,
                started_at=started_at,
            ),
            checkpoint=checkpoint,
        )

    async def advance(
        self,
        run_id: UUID,
        state: ThreadState,
        *,
        expected_engine: EngineKind,
        expected_version: int,
        result_payload: dict[str, JsonValue] | None = None,
        error_message: str | None = None,
    ) -> RuntimeCommit:
        target_status = state.status
        if target_status not in ACTIVE_STATUSES | TERMINAL_STATUSES:
            raise InvalidRunTransitionError(f"unsupported run status: {target_status.value}")
        if target_status in ACTIVE_STATUSES and (
            result_payload is not None or error_message is not None
        ):
            raise InvalidRunTransitionError("active runs cannot have a terminal outcome")
        if target_status is AgentStatus.ERROR and not error_message:
            raise InvalidRunTransitionError("error runs require an error message")
        if target_status is not AgentStatus.ERROR and error_message is not None:
            raise InvalidRunTransitionError("only error runs may persist an error message")

        async with self._session_factory() as session, session.begin():
            record = await session.get(RunRecord, run_id, with_for_update=True)
            if record is None:
                raise RunNotFoundError(f"run not found: {run_id}")
            if record.status not in {status.value for status in ACTIVE_STATUSES}:
                raise InvalidRunTransitionError(
                    f"run {run_id} is already terminal: {record.status}"
                )
            if record.thread_id != state.thread_id:
                raise RunStateMismatchError("run and state belong to different threads")
            if record.engine != expected_engine.value:
                raise RunEngineMismatchError("engine selection is immutable for a run")

            checkpoint = await self._checkpoint_store.append_in_transaction(
                session,
                state,
                expected_version=expected_version,
            )
            record.status = target_status.value
            if target_status in TERMINAL_STATUSES:
                record.result_payload = result_payload
                record.error_message = error_message
                record.finished_at = datetime.now(UTC)
            await session.flush()

            stored = self._project(record)
        return RuntimeCommit(run=stored, checkpoint=checkpoint)

    async def get(self, run_id: UUID) -> StoredRun:
        async with self._session_factory() as session:
            record = await session.get(RunRecord, run_id)
        if record is None:
            raise RunNotFoundError(f"run not found: {run_id}")
        return self._project(record)

    @staticmethod
    def _project(record: RunRecord) -> StoredRun:
        started_at = record.started_at
        if started_at.tzinfo is None:
            started_at = started_at.replace(tzinfo=UTC)
        return StoredRun(
            run_id=record.run_id,
            thread_id=record.thread_id,
            engine=EngineKind(record.engine),
            status=AgentStatus(record.status),
            started_at=started_at,
        )
