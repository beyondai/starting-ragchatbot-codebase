"""Tests for AIGenerator's tool-calling orchestration in backend/ai_generator.py."""

from unittest.mock import MagicMock, call

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
        "What is the capital of France?",
        tools=[{"name": "search_course_content"}],
        tool_manager=tool_manager,
    )

    assert result == "Paris is the capital of France."
    assert ai_generator.client.messages.create.call_count == 1
    tool_manager.execute_tool.assert_not_called()


def test_tool_use_triggers_search_course_content_with_correct_args(
    ai_generator, response_factory
):
    tool_use_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "search_course_content",
                {"query": "widgets", "course_name": "Test Course"},
                id="toolu_abc",
            )
        ],
    )
    followup_response = response_factory.response(
        "end_turn", [response_factory.text_block("Widgets rotate on an axle.")]
    )
    ai_generator.client.messages.create.side_effect = [
        tool_use_response,
        followup_response,
    ]

    tool_manager = MagicMock()
    tool_manager.execute_tool.return_value = (
        "[Test Course - Lesson 1]\nWidgets rotate on an axle."
    )

    result = ai_generator.generate_response(
        "How do widgets rotate?",
        tools=[{"name": "search_course_content"}],
        tool_manager=tool_manager,
    )

    tool_manager.execute_tool.assert_called_once_with(
        "search_course_content", query="widgets", course_name="Test Course"
    )
    assert result == "Widgets rotate on an axle."


def test_followup_call_includes_tool_result_with_matching_id(
    ai_generator, response_factory
):
    tool_use_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "search_course_content", {"query": "widgets"}, id="toolu_abc"
            )
        ],
    )
    followup_response = response_factory.response(
        "end_turn", [response_factory.text_block("done")]
    )
    ai_generator.client.messages.create.side_effect = [
        tool_use_response,
        followup_response,
    ]

    tool_manager = MagicMock()
    tool_manager.execute_tool.return_value = "search result content"

    ai_generator.generate_response(
        "How do widgets rotate?",
        tools=[{"name": "search_course_content"}],
        tool_manager=tool_manager,
    )

    second_call_kwargs = ai_generator.client.messages.create.call_args_list[1].kwargs
    messages = second_call_kwargs["messages"]
    tool_result_message = messages[-1]
    assert tool_result_message["role"] == "user"
    assert tool_result_message["content"] == [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_abc",
            "content": "search result content",
        }
    ]
    assistant_message = messages[-2]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["content"] == tool_use_response.content


def test_round_2_call_includes_tools_for_chaining(ai_generator, response_factory):
    """Round 2 must still offer tools/tool_choice so Claude can chain a
    second, different tool call after seeing round 1's results (e.g.
    get_course_outline -> search_course_content)."""
    tool_use_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "search_course_content", {"query": "widgets"}, id="toolu_abc"
            )
        ],
    )
    followup_response = response_factory.response(
        "end_turn", [response_factory.text_block("done")]
    )
    ai_generator.client.messages.create.side_effect = [
        tool_use_response,
        followup_response,
    ]

    tool_manager = MagicMock()
    tool_manager.execute_tool.return_value = "search result content"

    ai_generator.generate_response(
        "How do widgets rotate?",
        tools=[{"name": "search_course_content"}],
        tool_manager=tool_manager,
    )

    second_call_kwargs = ai_generator.client.messages.create.call_args_list[1].kwargs
    assert "tools" in second_call_kwargs
    assert second_call_kwargs["tool_choice"] == {"type": "auto"}


def test_two_sequential_tool_rounds_are_both_executed(ai_generator, response_factory):
    """The core new behavior: a second tool_use response is executed as a
    real round 2 (e.g. outline lookup -> content search), not treated as a
    dead end. A 3rd, tools-omitted call then synthesizes the final answer.
    """
    round1_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "get_course_outline", {"course_name": "Widgets"}, id="toolu_1"
            )
        ],
    )
    round2_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "search_course_content", {"query": "rotation"}, id="toolu_2"
            )
        ],
    )
    final_response = response_factory.response(
        "end_turn", [response_factory.text_block("Complete answer.")]
    )
    ai_generator.client.messages.create.side_effect = [
        round1_response,
        round2_response,
        final_response,
    ]

    tool_manager = MagicMock()
    tool_manager.execute_tool.side_effect = ["outline result", "search result"]

    result = ai_generator.generate_response(
        "Find a course covering the same topic as lesson 4",
        tools=[{"name": "get_course_outline"}, {"name": "search_course_content"}],
        tool_manager=tool_manager,
    )

    assert ai_generator.client.messages.create.call_count == 3
    assert tool_manager.execute_tool.call_args_list == [
        call("get_course_outline", course_name="Widgets"),
        call("search_course_content", query="rotation"),
    ]
    assert result == "Complete answer."


def test_final_synthesis_call_excludes_tools_and_tool_choice(
    ai_generator, response_factory
):
    round1_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "get_course_outline", {"course_name": "Widgets"}, id="toolu_1"
            )
        ],
    )
    round2_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "search_course_content", {"query": "rotation"}, id="toolu_2"
            )
        ],
    )
    final_response = response_factory.response(
        "end_turn", [response_factory.text_block("Complete answer.")]
    )
    ai_generator.client.messages.create.side_effect = [
        round1_response,
        round2_response,
        final_response,
    ]

    tool_manager = MagicMock()
    tool_manager.execute_tool.side_effect = ["outline result", "search result"]

    ai_generator.generate_response(
        "Find a course covering the same topic as lesson 4",
        tools=[{"name": "get_course_outline"}, {"name": "search_course_content"}],
        tool_manager=tool_manager,
    )

    third_call_kwargs = ai_generator.client.messages.create.call_args_list[2].kwargs
    assert "tools" not in third_call_kwargs
    assert "tool_choice" not in third_call_kwargs


def test_round_cap_enforced_third_tool_use_not_executed(ai_generator, response_factory):
    """Even if the final (tools-omitted) call misbehaves and returns another
    tool_use with no text, the cap holds: it's never executed, and
    _get_response returns that response immediately (no retry on tool_use),
    so the generic fallback is returned instead of a 3rd tool execution."""
    round1_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "search_course_content", {"query": "a"}, id="toolu_1"
            )
        ],
    )
    round2_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "search_course_content", {"query": "b"}, id="toolu_2"
            )
        ],
    )
    non_compliant_final_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "search_course_content", {"query": "c"}, id="toolu_3"
            )
        ],
    )
    ai_generator.client.messages.create.side_effect = [
        round1_response,
        round2_response,
        non_compliant_final_response,
    ]

    tool_manager = MagicMock()
    tool_manager.execute_tool.side_effect = ["result a", "result b"]

    result = ai_generator.generate_response(
        "some question",
        tools=[{"name": "search_course_content"}],
        tool_manager=tool_manager,
    )

    assert ai_generator.client.messages.create.call_count == 3
    assert tool_manager.execute_tool.call_count == 2
    assert (
        result
        == "I wasn't able to generate a response for that question — please try asking again."
    )


def test_tool_execution_exception_on_round_2_still_synthesizes_gracefully(
    ai_generator, response_factory
):
    """Same as the round-1 failure case, but the exception happens on round
    2 instead - the loop would end after round 2 regardless (cap reached),
    so this exercises the same is_error/graceful-synthesis path at the
    other call site where hard_failure is checked."""
    round1_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "search_course_content", {"query": "a"}, id="toolu_1"
            )
        ],
    )
    round2_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "get_course_outline", {"course_name": "Widgets"}, id="toolu_2"
            )
        ],
    )
    final_response = response_factory.response(
        "end_turn", [response_factory.text_block("Here's what I found.")]
    )
    ai_generator.client.messages.create.side_effect = [
        round1_response,
        round2_response,
        final_response,
    ]

    tool_manager = MagicMock()
    tool_manager.execute_tool.side_effect = ["result a", RuntimeError("outline boom")]

    result = ai_generator.generate_response(
        "some question",
        tools=[{"name": "search_course_content"}],
        tool_manager=tool_manager,
    )

    assert tool_manager.execute_tool.call_count == 2
    assert ai_generator.client.messages.create.call_count == 3

    final_call_kwargs = ai_generator.client.messages.create.call_args_list[2].kwargs
    tool_result = final_call_kwargs["messages"][-1]["content"][0]
    assert "Tool execution failed" in tool_result["content"]
    assert tool_result["is_error"] is True
    assert result == "Here's what I found."


def test_tool_execution_exception_terminates_rounds_gracefully(
    ai_generator, response_factory
):
    round1_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "search_course_content", {"query": "widgets"}, id="toolu_1"
            )
        ],
    )
    final_response = response_factory.response(
        "end_turn", [response_factory.text_block("Here's what I know.")]
    )
    ai_generator.client.messages.create.side_effect = [round1_response, final_response]

    tool_manager = MagicMock()
    tool_manager.execute_tool.side_effect = RuntimeError("boom")

    result = ai_generator.generate_response(
        "How do widgets rotate?",
        tools=[{"name": "search_course_content"}],
        tool_manager=tool_manager,
    )

    assert tool_manager.execute_tool.call_count == 1
    assert ai_generator.client.messages.create.call_count == 2

    final_call_kwargs = ai_generator.client.messages.create.call_args_list[1].kwargs
    tool_result = final_call_kwargs["messages"][-1]["content"][0]
    assert "Tool execution failed" in tool_result["content"]
    assert tool_result["is_error"] is True
    assert result == "Here's what I know."


def test_tool_returning_error_string_is_not_hard_failure(
    ai_generator, response_factory
):
    """A tool returning a normal error string (not raising) is an ordinary
    result - round 2 should still proceed with tools offered."""
    round1_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "search_course_content", {"query": "widgets"}, id="toolu_1"
            )
        ],
    )
    round2_response = response_factory.response(
        "end_turn", [response_factory.text_block("No luck there.")]
    )
    ai_generator.client.messages.create.side_effect = [round1_response, round2_response]

    tool_manager = MagicMock()
    tool_manager.execute_tool.return_value = "No relevant content found."

    result = ai_generator.generate_response(
        "How do widgets rotate?",
        tools=[{"name": "search_course_content"}],
        tool_manager=tool_manager,
    )

    second_call_kwargs = ai_generator.client.messages.create.call_args_list[1].kwargs
    assert "tools" in second_call_kwargs
    assert result == "No luck there."


def test_conversation_history_grows_correctly_across_two_rounds(
    ai_generator, response_factory
):
    round1_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "get_course_outline", {"course_name": "Widgets"}, id="toolu_1"
            )
        ],
    )
    round2_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "search_course_content", {"query": "rotation"}, id="toolu_2"
            )
        ],
    )
    final_response = response_factory.response(
        "end_turn", [response_factory.text_block("Complete answer.")]
    )
    ai_generator.client.messages.create.side_effect = [
        round1_response,
        round2_response,
        final_response,
    ]

    tool_manager = MagicMock()
    tool_manager.execute_tool.side_effect = ["outline result", "search result"]

    ai_generator.generate_response(
        "Find a course covering the same topic as lesson 4",
        tools=[{"name": "get_course_outline"}, {"name": "search_course_content"}],
        tool_manager=tool_manager,
    )

    final_call_kwargs = ai_generator.client.messages.create.call_args_list[2].kwargs
    messages = final_call_kwargs["messages"]
    assert len(messages) == 5
    assert messages[0] == {
        "role": "user",
        "content": "Find a course covering the same topic as lesson 4",
    }
    assert messages[1] == {"role": "assistant", "content": round1_response.content}
    assert messages[2] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "content": "outline result",
            }
        ],
    }
    assert messages[3] == {"role": "assistant", "content": round2_response.content}
    assert messages[4] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_2",
                "content": "search result",
            }
        ],
    }


def test_round_cap_is_configurable(ai_generator, response_factory):
    """Regression test for the extensibility the loop design was chosen
    for: lowering MAX_TOOL_ROUNDS changes how many rounds execute with no
    other code changes."""
    ai_generator.MAX_TOOL_ROUNDS = 1

    round1_response = response_factory.response(
        "tool_use",
        [
            response_factory.tool_use_block(
                "search_course_content", {"query": "widgets"}, id="toolu_1"
            )
        ],
    )
    final_response = response_factory.response(
        "end_turn", [response_factory.text_block("Answer after 1 round.")]
    )
    ai_generator.client.messages.create.side_effect = [round1_response, final_response]

    tool_manager = MagicMock()
    tool_manager.execute_tool.return_value = "search result"

    result = ai_generator.generate_response(
        "How do widgets rotate?",
        tools=[{"name": "search_course_content"}],
        tool_manager=tool_manager,
    )

    assert tool_manager.execute_tool.call_count == 1
    assert ai_generator.client.messages.create.call_count == 2
    assert result == "Answer after 1 round."


def test_blank_text_first_response_retries_and_returns_real_text_on_second(
    ai_generator, response_factory
):
    blank_response = response_factory.response(
        "end_turn", [response_factory.text_block("   ")]
    )
    real_response = response_factory.response(
        "end_turn", [response_factory.text_block("Here is your answer.")]
    )
    ai_generator.client.messages.create.side_effect = [blank_response, real_response]

    result = ai_generator.generate_response(
        "some question", tools=None, tool_manager=None
    )

    assert ai_generator.client.messages.create.call_count == 2
    assert result == "Here is your answer."


def test_max_attempts_exhausted_returns_fallback_message(
    ai_generator, response_factory
):
    blank_response = response_factory.response(
        "end_turn", [response_factory.text_block("")]
    )
    ai_generator.client.messages.create.side_effect = [blank_response, blank_response]

    result = ai_generator.generate_response(
        "some question", tools=None, tool_manager=None
    )

    assert ai_generator.client.messages.create.call_count == 2
    assert (
        result
        == "I wasn't able to generate a response for that question — please try asking again."
    )


def test_conversation_history_included_in_system_prompt(ai_generator, response_factory):
    response = response_factory.response(
        "end_turn", [response_factory.text_block("hello back")]
    )
    ai_generator.client.messages.create.return_value = response

    ai_generator.generate_response(
        "hi again",
        conversation_history="User: hi\nAssistant: hello\n",
        tools=None,
        tool_manager=None,
    )

    call_kwargs = ai_generator.client.messages.create.call_args.kwargs
    assert "User: hi\nAssistant: hello\n" in call_kwargs["system"]
    assert AIGenerator.SYSTEM_PROMPT in call_kwargs["system"]


def test_no_tools_passed_means_no_tools_key_in_api_params(
    ai_generator, response_factory
):
    response = response_factory.response(
        "end_turn", [response_factory.text_block("hi")]
    )
    ai_generator.client.messages.create.return_value = response

    ai_generator.generate_response("some question", tools=None, tool_manager=None)

    call_kwargs = ai_generator.client.messages.create.call_args.kwargs
    assert "tools" not in call_kwargs
    assert "tool_choice" not in call_kwargs
