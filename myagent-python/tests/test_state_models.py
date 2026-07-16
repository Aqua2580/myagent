import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from myagent.domain import (
    AgentStatus,
    ChatMessage,
    MessageType,
    ThreadState,
    TodoStatus,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_completed_java_state_round_trip_preserves_semantics() -> None:
    raw = load_fixture("thread_state_completed_java.json")

    state = ThreadState.model_validate(raw)
    restored = ThreadState.model_validate_json(state.to_java_json())

    assert restored.thread_id == "11111111-1111-4111-8111-111111111111"
    assert restored.status is AgentStatus.COMPLETED
    assert restored.messages[0].type is MessageType.USER
    assert restored.messages[1].tool_calls is not None
    assert restored.messages[1].tool_calls[0].name == "calculator"
    assert restored.messages[2].tool_responses is not None
    assert restored.messages[2].tool_responses[0].response_data == "4"
    assert restored.tool_calls[0].tool_call_id == "call-1"
    assert restored.token_usage.total_tokens == 150
    assert restored.todos[0].status is TodoStatus.COMPLETED


def test_java_serialization_uses_camel_case_and_explicit_nulls() -> None:
    state = ThreadState.model_validate(load_fixture("thread_state_completed_java.json"))

    payload = state.to_java_dict()

    assert "threadId" in payload
    assert "thread_id" not in payload
    assert "toolCalls" in payload["messages"][0]
    assert payload["messages"][0]["toolCalls"] is None
    assert payload["messages"][2]["toolResponses"][0]["responseData"] == "4"


def test_waiting_state_accepts_numeric_jackson_timestamps() -> None:
    state = ThreadState.model_validate(load_fixture("thread_state_waiting_java.json"))

    assert state.status is AgentStatus.WAITING_CONFIRMATION
    assert state.created_at == datetime.fromtimestamp(1784167200.0, UTC)
    assert state.metadata["guardrail.pending"]["toolName"] == "execute_shell"


def test_unknown_java_fields_survive_round_trip() -> None:
    state = ThreadState.model_validate(load_fixture("thread_state_waiting_java.json"))

    payload = state.to_java_dict()

    assert payload["futureTopLevelField"] == "must-survive-round-trip"
    assert payload["metadata"]["futureJavaField"] == {"preserve": True}


def test_new_thread_is_valid_and_keeps_python_control_data_in_metadata() -> None:
    state = ThreadState.new_thread("user-003")

    payload = state.to_java_dict()

    assert state.status is AgentStatus.RUNNING
    assert state.run_step_count == 0
    assert payload["metadata"]["stateSchemaVersion"] == 2
    assert payload["metadata"]["runStepCount"] == 0
    assert "runStepCount" not in payload


def test_increment_and_reset_keep_cumulative_steps_separate() -> None:
    state = ThreadState.new_thread("user-004")

    state.increment_step_count()
    state.increment_step_count()

    assert state.step_count == 2
    assert state.run_step_count == 2

    state.reset_run()

    assert state.step_count == 2
    assert state.run_step_count == 0


@pytest.mark.parametrize("field", ["threadId", "userId"])
def test_blank_identifiers_are_rejected(field: str) -> None:
    raw = load_fixture("thread_state_completed_java.json")
    raw[field] = "   "

    with pytest.raises(ValidationError):
        ThreadState.model_validate(raw)


def test_chat_message_factories_match_java_null_semantics() -> None:
    message = ChatMessage.assistant("done")

    assert message.to_java_dict() == {
        "type": "ASSISTANT",
        "content": "done",
        "toolCalls": None,
        "toolResponses": None,
    }
