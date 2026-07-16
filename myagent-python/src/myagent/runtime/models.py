"""Typed commands and results for the platform runtime service."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import ConfigDict, Field, JsonValue, field_validator

from myagent.domain.state import DomainModel, ThreadState


class EngineKind(StrEnum):
    """Execution engines supported by the platform runtime."""

    NATIVE = "native"
    LANGGRAPH = "langgraph"


class StartRunCommand(DomainModel):
    """Validated input used by FastAPI or a future TaskRouter to start a Run."""

    user_id: str = Field(min_length=1)
    engine: EngineKind
    input_message: str = Field(min_length=1)
    thread_id: UUID | None = None
    request_payload: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("user_id", "input_message")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("value must not be blank")
        return stripped


class RunSession(DomainModel):
    """Immutable Run identity plus a mutable, isolated engine state snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: UUID
    engine: EngineKind
    checkpoint_version: int = Field(ge=1)
    state: ThreadState
    started_at: datetime

    @field_validator("started_at")
    @classmethod
    def started_at_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("started_at must include timezone information")
        return value
