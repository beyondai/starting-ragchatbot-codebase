"""Tests for CourseOutlineTool.execute() in backend/search_tools.py."""


def test_execute_returns_formatted_outline_and_sets_last_sources(course_outline_tool):
    result = course_outline_tool.execute(course_name="Widgets")

    assert "Course Title: Test Course: Intro to Widgets" in result
    assert "0. Introduction" in result
    assert "1. Advanced Widgets" in result
    assert course_outline_tool.last_sources
    for source in course_outline_tool.last_sources:
        assert set(source.keys()) == {"text", "link"}
    assert course_outline_tool.last_sources == [
        {
            "text": "Test Course: Intro to Widgets",
            "link": "https://example.com/course",
        }
    ]


def test_execute_with_nonexistent_course_name_returns_error_and_no_sources(
    course_outline_tool,
):
    result = course_outline_tool.execute(course_name="Quantum Basketweaving")

    assert result == "No course found matching 'Quantum Basketweaving'."
    assert course_outline_tool.last_sources == []


def test_execute_multiple_calls_accumulate_last_sources(course_outline_tool):
    """Mirrors CourseSearchTool: a query comparing two courses' outlines
    should keep both rounds' sources rather than overwriting the first."""
    course_outline_tool.execute(course_name="Widgets")
    first_sources = list(course_outline_tool.last_sources)

    course_outline_tool.execute(course_name="Widgets")
    all_sources = course_outline_tool.last_sources

    assert len(all_sources) == len(first_sources) * 2
