import json
from datetime import datetime
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import ValidationError

from myagent.domain import (
    AgentStatus,
    ChatMessage,
    MessageRole,
    ThreadState,
    TodoStatus,
    TokenUsage,
    ToolCall,
    ToolResult,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_completed_state_round_trip_preserves_python_types() -> None:
    state = ThreadState.model_validate(load_fixture("thread_state_completed.json"))
    restored = ThreadState.model_validate_json(state.to_json())

    assert restored == state
    assert isinstance(restored.thread_id, UUID)
    assert restored.status is AgentStatus.COMPLETED
    assert restored.messages[0].role is MessageRole.USER
    assert restored.messages[1].tool_calls[0].arguments == {"expression": "2+2"}
    assert restored.messages[2].tool_results[0].content == 4
    assert restored.tool_audit[0].duration_ms == 25
    assert restored.token_usage.input_tokens == 100
    assert restored.todos[0].status is TodoStatus.COMPLETED


def test_serialization_is_snake_case_and_uses_lowercase_enums() -> None:
    state = ThreadState.model_validate(load_fixture("thread_state_completed.json"))

    payload = state.model_dump(mode="json")

    assert payload["thread_id"] == "11111111-1111-4111-8111-111111111111"
    assert payload["status"] == "completed"
    assert payload["token_usage"]["input_tokens"] == 100
    assert "threadId" not in payload
    assert "promptTokens" not in payload["token_usage"]


def test_waiting_confirmation_state_is_native_json() -> None:
    state = ThreadState.model_validate(load_fixture("thread_state_waiting.json"))

    assert state.status is AgentStatus.WAITING_CONFIRMATION
    assert state.messages[1].tool_calls[0].arguments == {"command_id": "list_workspace"}
    assert state.metadata["pending_confirmation"] == {
        "tool_call_id": "call-shell-1",
        "requested_by": "user-002",
    }


def test_new_thread_has_typed_uuid_and_timezone_aware_dates() -> None:
    state = ThreadState.new_thread("  user-003  ")

    assert isinstance(state.thread_id, UUID)
    assert state.user_id == "user-003"
    assert state.created_at.tzinfo is not None
    assert state.updated_at.tzinfo is not None
    assert state.schema_version == 1


def test_step_counters_are_first_class_fields() -> None:
    state = ThreadState.new_thread("user-004")

    state.increment_step_count()
    state.increment_step_count()

    assert state.total_step_count == 2
    assert state.run_step_count == 2

    state.start_run()

    assert state.total_step_count == 2
    assert state.run_step_count == 0
    assert state.status is AgentStatus.RUNNING


def test_token_usage_uses_input_output_vocabulary() -> None:
    usage = TokenUsage()

    usage.accumulate(input_tokens=20, output_tokens=5)
    usage.accumulate(input_tokens=10, output_tokens=2, total_tokens=20)

    assert usage.input_tokens == 30
    assert usage.output_tokens == 7
    assert usage.total_tokens == 45


def test_unknown_state_fields_are_rejected() -> None:
    raw = load_fixture("thread_state_completed.json")
    raw["unknown_field"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ThreadState.model_validate(raw)


def test_timezone_naive_state_dates_are_rejected() -> None:
    raw = load_fixture("thread_state_completed.json")
    raw["created_at"] = datetime(2026, 7, 16, 2, 0, 0)

    with pytest.raises(ValidationError, match="timezone"):
        ThreadState.model_validate(raw)


def test_role_specific_payloads_are_validated() -> None:
    call = ToolCall(id="call-1", name="calculator", arguments={"expression": "2+2"})

    with pytest.raises(ValidationError, match="assistant"):
        ChatMessage(role=MessageRole.USER, content="invalid", tool_calls=[call])

    result = ToolResult(tool_call_id="call-1", name="calculator", content=4)
    with pytest.raises(ValidationError, match="tool messages"):
        ChatMessage(role=MessageRole.ASSISTANT, tool_results=[result])


def test_message_factories_create_valid_native_models() -> None:
    call = ToolCall(id="call-1", name="calculator", arguments={"expression": "2+2"})
    result = ToolResult(tool_call_id="call-1", name="calculator", content=4)

    assistant = ChatMessage.assistant(tool_calls=[call])
    tool_message = ChatMessage.tool([result])

    assert assistant.role is MessageRole.ASSISTANT
    assert assistant.tool_calls == [call]
    assert tool_message.role is MessageRole.TOOL
    assert tool_message.tool_results == [result]
