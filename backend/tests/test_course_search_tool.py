"""Tests for CourseSearchTool.execute() in backend/search_tools.py."""


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


def test_execute_multiple_calls_accumulate_last_sources(course_search_tool):
    """Two rounds both calling search_course_content (e.g. a comparison
    query) must not lose the first round's sources - last_sources
    accumulates across execute() calls within one query; ToolManager.reset_sources()
    is what clears it between queries."""
    course_search_tool.execute(query="widget", lesson_number=0)
    first_sources = list(course_search_tool.last_sources)

    course_search_tool.execute(query="widget", lesson_number=1)
    all_sources = course_search_tool.last_sources

    assert len(all_sources) > len(first_sources)
    assert any("Lesson 0" in s["text"] for s in all_sources)
    assert any("Lesson 1" in s["text"] for s in all_sources)
