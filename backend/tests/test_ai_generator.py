"""Tests for AIGenerator's tool-calling orchestration in backend/ai_generator.py."""
from unittest.mock import MagicMock

import pytest

from ai_generator import AIGenerator


@pytest.fixture
def ai_generator(mocker):
    generator = AIGenerator(api_key="test-key", model="claude-sonnet-5")
    mocker.patch.object(generator.client, "messages")
    return generator


def test_no_tool_call_when_stop_reason_is_not_tool_use(ai_generator, response_factory):
    response = response_factory.response(
        "end_turn", [response_factory.text_block("Paris is the capital of France.")]
    )
    ai_generator.client.messages.create.return_value = response
    tool_manager = MagicMock()

    result = ai_generator.generate_response(
        "What is the capital of France?", tools=[{"name": "search_course_content"}], tool_manager=tool_manager
    )

    assert result == "Paris is the capital of France."
    assert ai_generator.client.messages.create.call_count == 1
    tool_manager.execute_tool.assert_not_called()


def test_tool_use_triggers_search_course_content_with_correct_args(ai_generator, response_factory):
    tool_use_response = response_factory.response(
        "tool_use",
        [response_factory.tool_use_block(
            "search_course_content", {"query": "widgets", "course_name": "Test Course"}, id="toolu_abc"
        )],
    )
    followup_response = response_factory.response(
        "end_turn", [response_factory.text_block("Widgets rotate on an axle.")]
    )
    ai_generator.client.messages.create.side_effect = [tool_use_response, followup_response]

    tool_manager = MagicMock()
    tool_manager.execute_tool.return_value = "[Test Course - Lesson 1]\nWidgets rotate on an axle."

    result = ai_generator.generate_response(
        "How do widgets rotate?", tools=[{"name": "search_course_content"}], tool_manager=tool_manager
    )

    tool_manager.execute_tool.assert_called_once_with(
        "search_course_content", query="widgets", course_name="Test Course"
    )
    assert result == "Widgets rotate on an axle."


def test_followup_call_includes_tool_result_with_matching_id(ai_generator, response_factory):
    tool_use_response = response_factory.response(
        "tool_use",
        [response_factory.tool_use_block("search_course_content", {"query": "widgets"}, id="toolu_abc")],
    )
    followup_response = response_factory.response("end_turn", [response_factory.text_block("done")])
    ai_generator.client.messages.create.side_effect = [tool_use_response, followup_response]

    tool_manager = MagicMock()
    tool_manager.execute_tool.return_value = "search result content"

    ai_generator.generate_response(
        "How do widgets rotate?", tools=[{"name": "search_course_content"}], tool_manager=tool_manager
    )

    second_call_kwargs = ai_generator.client.messages.create.call_args_list[1].kwargs
    messages = second_call_kwargs["messages"]
    tool_result_message = messages[-1]
    assert tool_result_message["role"] == "user"
    assert tool_result_message["content"] == [
        {"type": "tool_result", "tool_use_id": "toolu_abc", "content": "search result content"}
    ]
    assistant_message = messages[-2]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["content"] == tool_use_response.content


def test_followup_call_excludes_tools_and_tool_choice(ai_generator, response_factory):
    tool_use_response = response_factory.response(
        "tool_use",
        [response_factory.tool_use_block("search_course_content", {"query": "widgets"}, id="toolu_abc")],
    )
    followup_response = response_factory.response("end_turn", [response_factory.text_block("done")])
    ai_generator.client.messages.create.side_effect = [tool_use_response, followup_response]

    tool_manager = MagicMock()
    tool_manager.execute_tool.return_value = "search result content"

    ai_generator.generate_response(
        "How do widgets rotate?", tools=[{"name": "search_course_content"}], tool_manager=tool_manager
    )

    second_call_kwargs = ai_generator.client.messages.create.call_args_list[1].kwargs
    assert "tools" not in second_call_kwargs
    assert "tool_choice" not in second_call_kwargs


def test_followup_tool_use_with_no_text_falls_back_to_default_message(ai_generator, response_factory):
    """Regression test for the suspected bug: the follow-up call has no
    `tools`, and if Claude responds with another tool_use (no text) the
    code silently retries and returns the generic fallback instead of a
    real answer or a visible error.
    """
    tool_use_response = response_factory.response(
        "tool_use",
        [response_factory.tool_use_block("search_course_content", {"query": "widgets"}, id="toolu_abc")],
    )
    followup_tool_use_no_text = response_factory.response(
        "tool_use",
        [response_factory.tool_use_block("search_course_content", {"query": "widgets again"}, id="toolu_def")],
    )
    ai_generator.client.messages.create.side_effect = [
        tool_use_response,
        followup_tool_use_no_text,
        followup_tool_use_no_text,
    ]

    tool_manager = MagicMock()
    tool_manager.execute_tool.return_value = "search result content"

    result = ai_generator.generate_response(
        "How do widgets rotate?", tools=[{"name": "search_course_content"}], tool_manager=tool_manager
    )

    assert ai_generator.client.messages.create.call_count == 3
    assert result == "I wasn't able to generate a response for that question — please try asking again."


def test_blank_text_first_response_retries_and_returns_real_text_on_second(ai_generator, response_factory):
    blank_response = response_factory.response("end_turn", [response_factory.text_block("   ")])
    real_response = response_factory.response("end_turn", [response_factory.text_block("Here is your answer.")])
    ai_generator.client.messages.create.side_effect = [blank_response, real_response]

    result = ai_generator.generate_response("some question", tools=None, tool_manager=None)

    assert ai_generator.client.messages.create.call_count == 2
    assert result == "Here is your answer."


def test_max_attempts_exhausted_returns_fallback_message(ai_generator, response_factory):
    blank_response = response_factory.response("end_turn", [response_factory.text_block("")])
    ai_generator.client.messages.create.side_effect = [blank_response, blank_response]

    result = ai_generator.generate_response("some question", tools=None, tool_manager=None)

    assert ai_generator.client.messages.create.call_count == 2
    assert result == "I wasn't able to generate a response for that question — please try asking again."


def test_conversation_history_included_in_system_prompt(ai_generator, response_factory):
    response = response_factory.response("end_turn", [response_factory.text_block("hello back")])
    ai_generator.client.messages.create.return_value = response

    ai_generator.generate_response(
        "hi again", conversation_history="User: hi\nAssistant: hello\n", tools=None, tool_manager=None
    )

    call_kwargs = ai_generator.client.messages.create.call_args.kwargs
    assert "User: hi\nAssistant: hello\n" in call_kwargs["system"]
    assert AIGenerator.SYSTEM_PROMPT in call_kwargs["system"]


def test_no_tools_passed_means_no_tools_key_in_api_params(ai_generator, response_factory):
    response = response_factory.response("end_turn", [response_factory.text_block("hi")])
    ai_generator.client.messages.create.return_value = response

    ai_generator.generate_response("some question", tools=None, tool_manager=None)

    call_kwargs = ai_generator.client.messages.create.call_args.kwargs
    assert "tools" not in call_kwargs
    assert "tool_choice" not in call_kwargs
