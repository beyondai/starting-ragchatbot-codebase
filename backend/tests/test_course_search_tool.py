"""Tests for CourseSearchTool.execute() in backend/search_tools.py."""
import pytest


def test_execute_returns_formatted_results_and_sets_last_sources(course_search_tool):
    result = course_search_tool.execute(query="how do widgets rotate")

    assert "[Test Course: Intro to Widgets - Lesson" in result
    assert course_search_tool.last_sources
    for source in course_search_tool.last_sources:
        assert set(source.keys()) == {"text", "link"}


def test_execute_with_course_name_fuzzy_match(course_search_tool):
    result = course_search_tool.execute(query="rotation", course_name="Widgets")

    assert "Test Course: Intro to Widgets" in result


def test_execute_with_lesson_number_filter(course_search_tool):
    result = course_search_tool.execute(query="widget", lesson_number=1)

    assert "Lesson 1" in result
    assert "Lesson 0" not in result


def test_execute_with_course_and_lesson_filter_combined(course_search_tool):
    result = course_search_tool.execute(
        query="widget", course_name="Widgets", lesson_number=0
    )

    assert "Lesson 0" in result
    assert "Lesson 1" not in result


@pytest.mark.xfail(
    strict=True,
    reason=(
        "BUG: VectorStore._resolve_course_name has no similarity threshold — "
        "Chroma's n_results=1 query always returns the nearest course in a "
        "non-empty catalog, so an unrelated/misspelled course_name silently "
        "resolves to some course instead of failing. 'No course found matching' "
        "is unreachable whenever the catalog is non-empty."
    ),
)
def test_execute_with_nonexistent_course_name_returns_exact_error_string(course_search_tool):
    result = course_search_tool.execute(query="anything", course_name="Quantum Basketweaving")

    assert result == "No course found matching 'Quantum Basketweaving'"
    assert course_search_tool.last_sources == []


def test_execute_with_valid_filters_but_zero_matches_returns_no_content_message(course_search_tool):
    result = course_search_tool.execute(
        query="widget", course_name="Widgets", lesson_number=99
    )

    # filter_info uses the raw course_name argument as typed, not the
    # resolved course title (see search_tools.py _format_results).
    assert result == "No relevant content found in course 'Widgets' in lesson 99."


def test_execute_search_error_from_chroma_exception_passes_through(course_search_tool, vector_store, mocker):
    mocker.patch.object(vector_store.course_content, "query", side_effect=Exception("boom"))

    result = course_search_tool.execute(query="anything")

    assert result == "Search error: boom"


def test_execute_multiple_calls_overwrite_last_sources(course_search_tool):
    course_search_tool.execute(query="widget", lesson_number=0)
    first_sources = course_search_tool.last_sources

    course_search_tool.execute(query="widget", lesson_number=1)
    second_sources = course_search_tool.last_sources

    assert first_sources != second_sources
    assert all("Lesson 1" in s["text"] for s in second_sources)
