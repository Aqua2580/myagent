"""SQLAlchemy persistence models for the Python-native platform."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
JSON_PAYLOAD = JSON().with_variant(JSONB(), "postgresql")


def utc_now() -> datetime:
    """Return an aware UTC timestamp for application-side defaults."""

    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Declarative base with deterministic constraint names for Alembic."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class ThreadRecord(Base):
    """Durable identity and current summary for an agent thread."""

    __tablename__ = "agent_threads"
    __table_args__ = (
        CheckConstraint(
            "current_checkpoint_version >= 0",
            name="current_checkpoint_version_non_negative",
        ),
        CheckConstraint("total_step_count >= 0", name="total_step_count_non_negative"),
        Index("ix_agent_threads_user_updated", "user_id", "updated_at"),
    )

    thread_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_checkpoint_version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_step_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    runs: Mapped[list[RunRecord]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    checkpoints: Mapped[list[CheckpointRecord]] = relationship(
        back_populates="thread",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class RunRecord(Base):
    """One immutable engine selection and its execution outcome."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("ix_agent_runs_thread_started", "thread_id", "started_at"),
        CheckConstraint("engine IN ('native', 'langgraph')", name="known_engine"),
    )

    run_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    thread_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_threads.thread_id", ondelete="CASCADE"),
        nullable=False,
    )
    engine: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    request_payload: Mapped[dict[str, Any]] = mapped_column(
        JSON_PAYLOAD, default=dict, nullable=False
    )
    result_payload: Mapped[dict[str, Any] | None] = mapped_column(
        JSON_PAYLOAD, nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    thread: Mapped[ThreadRecord] = relationship(back_populates="runs")


class CheckpointRecord(Base):
    """Append-only durable snapshot for recovery and audit."""

    __tablename__ = "agent_checkpoints"
    __table_args__ = (
        UniqueConstraint("thread_id", "version", name="thread_version"),
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint("state_schema_version > 0", name="schema_version_positive"),
        Index("ix_agent_checkpoints_thread_created", "thread_id", "created_at"),
    )

    checkpoint_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid4
    )
    thread_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agent_threads.thread_id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    state_schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    state_payload: Mapped[dict[str, Any]] = mapped_column(JSON_PAYLOAD, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    thread: Mapped[ThreadRecord] = relationship(back_populates="checkpoints")
