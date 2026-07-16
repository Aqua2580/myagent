"""Durable SQL checkpoints and Redis hot-state caching."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from redis.asyncio import Redis
from redis.exceptions import RedisError, WatchError
from sqlalchemy import delete, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from myagent.config import Settings
from myagent.domain import ThreadState
from myagent.persistence.database import AsyncSessionFactory
from myagent.persistence.models import CheckpointRecord, RunRecord, ThreadRecord

logger = logging.getLogger(__name__)


class CheckpointEnvelope(BaseModel):
    """Versioned payload shared by the SQL archive and Redis cache."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    state: ThreadState
    saved_at: datetime

    @field_validator("saved_at")
    @classmethod
    def saved_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("saved_at must include timezone information")
        return value


class CheckpointConflictError(RuntimeError):
    """Raised when optimistic checkpoint version validation fails."""


class CheckpointOwnershipError(RuntimeError):
    """Raised when a checkpoint attempts to change a thread owner."""


class SqlCheckpointStore:
    """Append-only checkpoint archive backed by an async SQLAlchemy session."""

    def __init__(self, session_factory: AsyncSessionFactory) -> None:
        self._session_factory = session_factory

    async def save(
        self,
        state: ThreadState,
        *,
        expected_version: int | None = None,
    ) -> CheckpointEnvelope:
        """Append a snapshot and atomically advance the thread version."""

        async with self._session_factory() as session:
            try:
                async with session.begin():
                    envelope = await self.append_in_transaction(
                        session,
                        state,
                        expected_version=expected_version,
                    )
            except IntegrityError as exc:
                raise CheckpointConflictError("checkpoint version already exists") from exc

        return envelope

    async def append_in_transaction(
        self,
        session: AsyncSession,
        state: ThreadState,
        *,
        expected_version: int | None = None,
    ) -> CheckpointEnvelope:
        """Append a checkpoint inside the caller's active SQL transaction."""

        snapshot = state.model_copy(deep=True)
        saved_at = datetime.now(UTC)
        thread = await session.get(
            ThreadRecord,
            snapshot.thread_id,
            with_for_update=True,
        )
        current_version = thread.current_checkpoint_version if thread else 0
        if expected_version is not None and expected_version != current_version:
            raise CheckpointConflictError(
                f"expected checkpoint version {expected_version}, found {current_version}"
            )

        next_version = current_version + 1
        if thread is None:
            thread = ThreadRecord(
                thread_id=snapshot.thread_id,
                user_id=snapshot.user_id,
                status=snapshot.status.value,
                current_checkpoint_version=next_version,
                total_step_count=snapshot.total_step_count,
                created_at=snapshot.created_at,
                updated_at=snapshot.updated_at,
            )
            session.add(thread)
        else:
            if thread.user_id != snapshot.user_id:
                raise CheckpointOwnershipError("thread owner cannot be changed")
            thread.status = snapshot.status.value
            thread.current_checkpoint_version = next_version
            thread.total_step_count = snapshot.total_step_count
            thread.updated_at = snapshot.updated_at

        session.add(
            CheckpointRecord(
                thread_id=snapshot.thread_id,
                version=next_version,
                state_schema_version=snapshot.schema_version,
                state_payload=snapshot.model_dump(mode="json"),
                created_at=saved_at,
            )
        )
        await session.flush()
        return CheckpointEnvelope(version=next_version, state=snapshot, saved_at=saved_at)

    async def load(self, thread_id: UUID) -> CheckpointEnvelope | None:
        """Load the newest durable checkpoint for a thread."""

        statement = (
            select(CheckpointRecord)
            .where(CheckpointRecord.thread_id == thread_id)
            .order_by(CheckpointRecord.version.desc())
            .limit(1)
        )
        async with self._session_factory() as session:
            record = await session.scalar(statement)
        if record is None:
            return None
        return CheckpointEnvelope(
            version=record.version,
            state=ThreadState.model_validate(record.state_payload),
            saved_at=(
                record.created_at
                if record.created_at.tzinfo is not None
                else record.created_at.replace(tzinfo=UTC)
            ),
        )

    async def delete(self, thread_id: UUID) -> bool:
        """Delete a thread and its history consistently across SQL dialects."""

        async with self._session_factory() as session, session.begin():
            await session.execute(
                delete(CheckpointRecord).where(CheckpointRecord.thread_id == thread_id)
            )
            await session.execute(delete(RunRecord).where(RunRecord.thread_id == thread_id))
            result = cast(
                CursorResult[Any],
                await session.execute(
                    delete(ThreadRecord).where(ThreadRecord.thread_id == thread_id)
                ),
            )
        return result.rowcount > 0


class RedisCheckpointCache:
    """Version-aware Redis cache for active thread checkpoints."""

    def __init__(
        self,
        client: Redis,
        *,
        key_prefix: str,
        ttl_seconds: int,
        owns_client: bool = False,
    ) -> None:
        self._client = client
        self._key_prefix = key_prefix.rstrip(":")
        self._ttl_seconds = ttl_seconds
        self._owns_client = owns_client

    @classmethod
    def from_url(
        cls,
        url: str,
        *,
        key_prefix: str,
        ttl_seconds: int,
    ) -> RedisCheckpointCache:
        client = Redis.from_url(url, decode_responses=True)
        return cls(
            client,
            key_prefix=key_prefix,
            ttl_seconds=ttl_seconds,
            owns_client=True,
        )

    @classmethod
    def from_settings(cls, settings: Settings) -> RedisCheckpointCache:
        return cls.from_url(
            settings.redis_url.get_secret_value(),
            key_prefix=settings.checkpoint_key_prefix,
            ttl_seconds=settings.checkpoint_ttl_seconds,
        )

    def key_for(self, thread_id: UUID) -> str:
        return f"{self._key_prefix}:{thread_id}"

    async def put(self, envelope: CheckpointEnvelope, *, max_retries: int = 3) -> bool:
        """Cache only newer versions using Redis optimistic transactions."""

        key = self.key_for(envelope.state.thread_id)
        for attempt in range(max_retries):
            async with self._client.pipeline(transaction=True) as pipeline:
                try:
                    await pipeline.watch(key)
                    raw = await pipeline.get(key)
                    try:
                        current = self._decode(raw)
                    except (TypeError, ValueError, ValidationError):
                        logger.warning("Replacing invalid Redis checkpoint at %s", key)
                        current = None
                    if current is not None and current.version >= envelope.version:
                        return False
                    pipeline.multi()  # type: ignore[no-untyped-call]
                    pipeline.set(key, envelope.model_dump_json(), ex=self._ttl_seconds)
                    await pipeline.execute()
                    return True
                except WatchError:
                    if attempt + 1 == max_retries:
                        raise
        return False

    async def load(self, thread_id: UUID) -> CheckpointEnvelope | None:
        key = self.key_for(thread_id)
        raw = await self._client.get(key)
        try:
            return self._decode(raw)
        except (TypeError, ValueError, ValidationError):
            logger.warning("Discarding invalid Redis checkpoint at %s", key)
            await self._client.delete(key)
            return None

    async def delete(self, thread_id: UUID) -> bool:
        return bool(await self._client.delete(self.key_for(thread_id)))

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _decode(raw: bytes | str | None) -> CheckpointEnvelope | None:
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        return CheckpointEnvelope.model_validate_json(raw)


class Checkpointer:
    """Coordinate durable SQL snapshots with a best-effort Redis hot cache."""

    def __init__(self, store: SqlCheckpointStore, cache: RedisCheckpointCache) -> None:
        self._store = store
        self._cache = cache

    async def save(
        self,
        state: ThreadState,
        *,
        expected_version: int | None = None,
    ) -> CheckpointEnvelope:
        envelope = await self._store.save(state, expected_version=expected_version)
        await self.publish(envelope)
        return envelope

    async def publish(self, envelope: CheckpointEnvelope) -> None:
        """Publish an already committed SQL checkpoint to the hot cache."""

        try:
            await self._cache.put(envelope)
        except RedisError:
            logger.warning("Redis checkpoint refresh failed", exc_info=True)

    async def load_hot(self, thread_id: UUID) -> CheckpointEnvelope | None:
        """Load Redis first and fall back to the durable SQL archive."""

        try:
            cached = await self._cache.load(thread_id)
        except RedisError:
            logger.warning("Redis checkpoint read failed", exc_info=True)
            cached = None
        if cached is not None:
            return cached

        durable = await self._store.load(thread_id)
        if durable is not None:
            try:
                await self._cache.put(durable)
            except RedisError:
                logger.warning("Redis checkpoint warm-up failed", exc_info=True)
        return durable

    async def load_durable(self, thread_id: UUID) -> CheckpointEnvelope | None:
        """Bypass Redis for recovery, audit, and consistency-sensitive reads."""

        return await self._store.load(thread_id)

    async def delete(self, thread_id: UUID) -> bool:
        deleted = await self._store.delete(thread_id)
        try:
            await self._cache.delete(thread_id)
        except RedisError:
            logger.warning("Redis checkpoint delete failed", exc_info=True)
        return deleted
