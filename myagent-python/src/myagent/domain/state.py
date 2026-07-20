"""Python-native conversation and agent runtime state models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal, Self
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator


class DomainModel(BaseModel):
    """Strict base model shared by runtime state objects."""

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )


class AgentStatus(StrEnum):
    RUNNING = "running"
    WAITING_CONFIRMATION = "waiting_confirmation"
    COMPLETED = "completed"
    PARTIAL_COMPLETED = "partial_completed"
    ERROR = "error"
    CANCELLED = "cancelled"


class MessageRole(StrEnum):
    USER = "user"
    SYSTEM = "system"
    ASSISTANT = "assistant"
    TOOL = "tool"


class TodoStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ToolCall(DomainModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    arguments: dict[str, JsonValue] = Field(default_factory=dict)


class ToolResult(DomainModel):
    tool_call_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    content: JsonValue
    is_error: bool = False


class ChatMessage(DomainModel):
    role: MessageRole
    content: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_role_payload(self) -> Self:
        if self.tool_calls and self.role is not MessageRole.ASSISTANT:
            raise ValueError("tool_calls are only valid on assistant messages")
        if self.tool_results and self.role is not MessageRole.TOOL:
            raise ValueError("tool_results are only valid on tool messages")
        return self

    @classmethod
    def user(cls, content: str) -> Self:
        return cls(role=MessageRole.USER, content=content)

    @classmethod
    def system(cls, content: str) -> Self:
        return cls(role=MessageRole.SYSTEM, content=content)

    @classmethod
    def assistant(
        cls,
        content: str | None = None,
        *,
        tool_calls: list[ToolCall] | None = None,
    ) -> Self:
        return cls(
            role=MessageRole.ASSISTANT,
            content=content,
            tool_calls=tool_calls or [],
        )

    @classmethod
    def tool(cls, results: list[ToolResult]) -> Self:
        return cls(role=MessageRole.TOOL, tool_results=results)


class ToolAuditEntry(DomainModel):
    call: ToolCall
    result: ToolResult | None = None
    started_at: datetime
    finished_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)

    @field_validator("started_at", "finished_at")
    @classmethod
    def datetimes_must_be_timezone_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("datetime must include timezone information")
        return value


class TokenUsage(DomainModel):
    input_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)

    def accumulate(
        self,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        total_tokens: int | None = None,
    ) -> None:
        total = total_tokens if total_tokens is not None else input_tokens + output_tokens
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.total_tokens += total


class TodoItem(DomainModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    status: TodoStatus = TodoStatus.PENDING


class ThreadState(DomainModel):
    """Platform-owned state shared by Native and LangGraph engine adapters."""

    schema_version: Literal[1] = 1
    thread_id: UUID
    user_id: str = Field(min_length=1)
    messages: list[ChatMessage] = Field(default_factory=list)
    tool_audit: list[ToolAuditEntry] = Field(default_factory=list)
    total_step_count: int = Field(default=0, ge=0)
    run_step_count: int = Field(default=0, ge=0)
    status: AgentStatus = AgentStatus.RUNNING
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    todos: list[TodoItem] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @field_validator("user_id")
    @classmethod
    def user_id_must_not_be_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("user_id must not be blank")
        return stripped

    @field_validator("created_at", "updated_at")
    @classmethod
    def state_datetimes_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("datetime must include timezone information")
        return value

    @classmethod
    def new_thread(cls, user_id: str) -> Self:
        now = datetime.now(UTC)
        return cls(
            thread_id=uuid4(),
            user_id=user_id,
            created_at=now,
            updated_at=now,
        )

    def start_run(self) -> None:
        self.run_step_count = 0
        self.status = AgentStatus.RUNNING
        self.metadata.pop("step_warning_injected", None)
        self.updated_at = datetime.now(UTC)

    def increment_step_count(self) -> None:
        self.total_step_count += 1
        self.run_step_count += 1
        self.updated_at = datetime.now(UTC)

    def to_json(self) -> str:
        return self.model_dump_json()
