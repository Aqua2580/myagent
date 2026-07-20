"""Platform service that owns Thread state and Run lifecycle transitions."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from pydantic import JsonValue

from myagent.domain import AgentStatus, ChatMessage, ThreadState
from myagent.persistence import Checkpointer
from myagent.runtime.errors import (
    InvalidRunTransitionError,
    ThreadAccessDeniedError,
    ThreadNotFoundError,
)
from myagent.runtime.models import RunSession, StartRunCommand
from myagent.runtime.repository import ACTIVE_STATUSES, RuntimeCommit, RuntimeRepository


class RunService:
    """Stable platform entrypoint shared by APIs and execution engines."""

    def __init__(self, repository: RuntimeRepository, checkpointer: Checkpointer) -> None:
        self._repository = repository
        self._checkpointer = checkpointer

    async def start_run(self, command: StartRunCommand) -> RunSession:
        if command.thread_id is None:
            state = ThreadState.new_thread(command.user_id)
            expected_version = 0
        else:
            durable = await self._checkpointer.load_durable(command.thread_id)
            if durable is None:
                raise ThreadNotFoundError(f"thread not found: {command.thread_id}")
            if durable.state.user_id != command.user_id:
                raise ThreadAccessDeniedError("thread belongs to another user")
            state = durable.state.model_copy(deep=True)
            expected_version = durable.version

        state.start_run()
        state.messages.append(ChatMessage.user(command.input_message))
        state.updated_at = datetime.now(UTC)
        commit = await self._repository.start(
            state,
            engine=command.engine,
            input_message=command.input_message,
            request_payload=command.request_payload,
            expected_version=expected_version,
        )
        return await self._publish(commit)

    async def save_progress(self, run: RunSession) -> RunSession:
        if run.state.status not in ACTIVE_STATUSES:
            raise InvalidRunTransitionError(
                "save_progress only accepts running or waiting_confirmation state"
            )
        state = run.state.model_copy(deep=True)
        state.updated_at = datetime.now(UTC)
        commit = await self._repository.advance(
            run.run_id,
            state,
            expected_engine=run.engine,
            expected_version=run.checkpoint_version,
        )
        return await self._publish(commit)

    async def complete_run(
        self,
        run: RunSession,
        *,
        result_payload: dict[str, JsonValue] | None = None,
        partial: bool = False,
    ) -> RunSession:
        status = AgentStatus.PARTIAL_COMPLETED if partial else AgentStatus.COMPLETED
        return await self._finish(run, status=status, result_payload=result_payload)

    async def fail_run(self, run: RunSession, *, error_message: str) -> RunSession:
        sanitized = error_message.strip()
        if not sanitized:
            raise ValueError("error_message must not be blank")
        return await self._finish(
            run,
            status=AgentStatus.ERROR,
            error_message=sanitized[:4000],
        )

    async def cancel_run(self, run: RunSession) -> RunSession:
        return await self._finish(run, status=AgentStatus.CANCELLED)

    async def resume_run(self, run_id: UUID, *, user_id: str) -> RunSession:
        stored = await self._repository.get(run_id)
        if stored.status not in ACTIVE_STATUSES:
            raise InvalidRunTransitionError(f"run {run_id} is already terminal")
        durable = await self._checkpointer.load_durable(stored.thread_id)
        if durable is None:
            raise ThreadNotFoundError(f"thread not found: {stored.thread_id}")
        if durable.state.user_id != user_id.strip():
            raise ThreadAccessDeniedError("thread belongs to another user")
        return RunSession(
            run_id=stored.run_id,
            engine=stored.engine,
            checkpoint_version=durable.version,
            state=durable.state.model_copy(deep=True),
            started_at=stored.started_at,
        )

    async def _finish(
        self,
        run: RunSession,
        *,
        status: AgentStatus,
        result_payload: dict[str, JsonValue] | None = None,
        error_message: str | None = None,
    ) -> RunSession:
        state = run.state.model_copy(deep=True)
        state.status = status
        state.updated_at = datetime.now(UTC)
        commit = await self._repository.advance(
            run.run_id,
            state,
            expected_engine=run.engine,
            expected_version=run.checkpoint_version,
            result_payload=result_payload,
            error_message=error_message,
        )
        return await self._publish(commit)

    async def _publish(self, commit: RuntimeCommit) -> RunSession:
        await self._checkpointer.publish(commit.checkpoint)
        return RunSession(
            run_id=commit.run.run_id,
            engine=commit.run.engine,
            checkpoint_version=commit.checkpoint.version,
            state=commit.checkpoint.state.model_copy(deep=True),
            started_at=commit.run.started_at,
        )
