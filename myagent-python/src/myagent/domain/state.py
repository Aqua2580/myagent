"""Java-compatible conversation and agent state models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class JavaCompatibleModel(BaseModel):
    """Base model that reads Python names and emits Java camelCase names."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        extra="allow",
        populate_by_name=True,
        validate_assignment=True,
    )

    def to_java_dict(self) -> dict[str, Any]:
        """Serialize with the field names expected by the Java ObjectMapper."""

        return self.model_dump(mode="json", by_alias=True, exclude_none=False)

    def to_java_json(self) -> str:
        """Serialize as compact JSON accepted by the Java state reader."""

        return self.model_dump_json(by_alias=True, exclude_none=False)


class AgentStatus(StrEnum):
    RUNNING = "RUNNING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    COMPLETED = "COMPLETED"
    PARTIAL_COMPLETED = "PARTIAL_COMPLETED"
    ERROR = "ERROR"


class MessageType(StrEnum):
    USER = "USER"
    SYSTEM = "SYSTEM"
    ASSISTANT = "ASSISTANT"
    TOOL = "TOOL"


class TodoStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class ToolCallData(JavaCompatibleModel):
    id: str
    type: str
    name: str
    arguments: str


class ToolResponseData(JavaCompatibleModel):
    id: str
    name: str
    response_data: str


class ChatMessage(JavaCompatibleModel):
    type: MessageType
    content: str | None = None
    tool_calls: list[ToolCallData] | None = None
    tool_responses: list[ToolResponseData] | None = None

    @classmethod
    def user(cls, content: str) -> Self:
        return cls(type=MessageType.USER, content=content)

    @classmethod
    def system(cls, content: str) -> Self:
        return cls(type=MessageType.SYSTEM, content=content)

    @classmethod
    def assistant(
        cls,
        content: str | None,
        tool_calls: list[ToolCallData] | None = None,
    ) -> Self:
        return cls(type=MessageType.ASSISTANT, content=content, tool_calls=tool_calls)

    @classmethod
    def tool(cls, responses: list[ToolResponseData]) -> Self:
        return cls(type=MessageType.TOOL, tool_responses=responses)


class ToolCallRecord(JavaCompatibleModel):
    tool_call_id: str
    tool_name: str
    arguments: str
    result: str | None = None
    error: str | None = None
    called_at: datetime | None = None


class TokenUsage(JavaCompatibleModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)

    def accumulate(
        self,
        prompt_tokens: int | None,
        completion_tokens: int | None,
        total_tokens: int | None = None,
    ) -> None:
        """Mirror Java TokenUsage.accumulate while tolerating missing provider values."""

        prompt = prompt_tokens or 0
        completion = completion_tokens or 0
        total = total_tokens if total_tokens is not None else prompt + completion
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.total_tokens += total


class TodoItem(JavaCompatibleModel):
    id: str
    title: str
    status: TodoStatus


class ThreadState(JavaCompatibleModel):
    """Serializable state shared by NativeAgentEngine and the platform layer."""

    thread_id: str
    user_id: str
    messages: list[ChatMessage] = Field(default_factory=list)
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    step_count: int = Field(default=0, ge=0)
    status: AgentStatus = AgentStatus.RUNNING
    token_usage: TokenUsage = Field(default_factory=TokenUsage)
    todos: list[TodoItem] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("thread_id", "user_id")
    @classmethod
    def identifiers_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identifier must not be blank")
        return value

    @classmethod
    def new_thread(cls, user_id: str) -> Self:
        """Create a valid state without adding Python-only top-level JSON fields."""

        now = datetime.now(UTC)
        return cls(
            thread_id=str(uuid4()),
            user_id=user_id,
            created_at=now,
            updated_at=now,
            metadata={"stateSchemaVersion": 2, "runStepCount": 0},
        )

    @property
    def run_step_count(self) -> int:
        """Return the per-run counter stored inside Java-compatible metadata."""

        value = self.metadata.get("runStepCount", 0)
        return int(value) if isinstance(value, int | float | str) else 0

    def reset_run(self) -> None:
        """Reset only per-run control data; preserve cumulative Java stepCount."""

        self.metadata["runStepCount"] = 0
        self.metadata.pop("stepWarningInjected", None)

    def increment_step_count(self) -> None:
        """Increment cumulative and per-run counters and refresh updatedAt."""

        self.step_count += 1
        self.metadata["runStepCount"] = self.run_step_count + 1
        self.updated_at = datetime.now(UTC)
