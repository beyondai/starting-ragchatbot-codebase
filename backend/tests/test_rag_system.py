"""Tests for RAGSystem.query()'s handling of content-related queries, in backend/rag_system.py."""
import pytest

from rag_system import RAGSystem


@pytest.fixture
def rag_system(fake_config, sample_course, sample_chunks, mocker):
    system = RAGSystem(fake_config)
    system.vector_store.add_course_metadata(sample_course)
    system.vector_store.add_course_content(sample_chunks)
    mocker.patch.object(system.ai_generator, "generate_response")
    return system


def test_content_query_triggers_search_tool_and_returns_sources(rag_system):
    def fake_generate_response(query, conversation_history=None, tools=None, tool_manager=None):
        tool_manager.execute_tool("search_course_content", query="widget rotation")
        return "Widgets rotate on an axle."

    rag_system.ai_generator.generate_response.side_effect = fake_generate_response

    response, sources = rag_system.query("Tell me about widget rotation")

    assert response == "Widgets rotate on an axle."
    assert sources
    for source in sources:
        assert set(source.keys()) == {"text", "link"}


def test_general_knowledge_query_never_invokes_search(rag_system, mocker):
    rag_system.ai_generator.generate_response.return_value = "The sky is blue due to Rayleigh scattering."
    spy = mocker.spy(rag_system.tool_manager, "execute_tool")

    response, sources = rag_system.query("Why is the sky blue?")

    assert response == "The sky is blue due to Rayleigh scattering."
    assert sources == []
    spy.assert_not_called()


def test_sources_reset_between_calls(rag_system):
    def fake_generate_response(query, conversation_history=None, tools=None, tool_manager=None):
        tool_manager.execute_tool("search_course_content", query="widget rotation")
        return "answer with sources"

    rag_system.ai_generator.generate_response.side_effect = fake_generate_response
    _, first_sources = rag_system.query("Tell me about widget rotation")
    assert first_sources

    rag_system.ai_generator.generate_response.side_effect = None
    rag_system.ai_generator.generate_response.return_value = "general answer, no search"
    _, second_sources = rag_system.query("What is 2 + 2?")

    assert second_sources == []


def test_session_history_passed_to_ai_generator_on_second_call(rag_system):
    rag_system.ai_generator.generate_response.return_value = "first answer"
    rag_system.query("first question", session_id="session_1")

    rag_system.ai_generator.generate_response.return_value = "second answer"
    rag_system.query("second question", session_id="session_1")

    second_call_kwargs = rag_system.ai_generator.generate_response.call_args_list[1].kwargs
    history = second_call_kwargs["conversation_history"]
    assert history is not None
    assert "first question" in history
    assert "first answer" in history


def test_query_wraps_prompt_before_passing_to_ai_generator(rag_system):
    rag_system.ai_generator.generate_response.return_value = "an answer"

    rag_system.query("What is a widget?")

    call_kwargs = rag_system.ai_generator.generate_response.call_args.kwargs
    assert call_kwargs["query"] == "Answer this question about course materials: What is a widget?"


def test_query_without_session_id_does_not_create_session(rag_system):
    rag_system.ai_generator.generate_response.return_value = "an answer"

    rag_system.query("some question")

    assert rag_system.session_manager.sessions == {}


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG: VectorStore._resolve_course_name has no similarity threshold — "
        "a non-empty catalog always resolves any course_name to its nearest "
        "neighbor, so this never reaches the 'No course found matching' path. "
        "See test_course_search_tool.py for the isolated repro."
    ),
)
def test_content_query_with_unresolvable_course_surfaces_no_course_found(rag_system):
    def fake_generate_response(query, conversation_history=None, tools=None, tool_manager=None):
        return tool_manager.execute_tool(
            "search_course_content", query="anything", course_name="Nonexistent Course XYZ"
        )

    rag_system.ai_generator.generate_response.side_effect = fake_generate_response

    response, sources = rag_system.query("Tell me about Nonexistent Course XYZ")

    assert response == "No course found matching 'Nonexistent Course XYZ'"
    assert sources == []
