"""Shared fixtures for the backend test suite.

Never imports backend/app.py: that module constructs a real RAGSystem
against the live ./chroma_db at import time and mounts StaticFiles
relative to CWD. Tests instead build VectorStore/RAGSystem directly
against an isolated tmp_path-based Chroma dir.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from models import Course, Lesson, CourseChunk
from vector_store import VectorStore
from search_tools import CourseSearchTool, CourseListTool, CourseOutlineTool, ToolManager


@pytest.fixture
def tmp_chroma_path(tmp_path):
    return str(tmp_path / "chroma_db_test")


@pytest.fixture
def sample_course():
    return Course(
        title="Test Course: Intro to Widgets",
        course_link="https://example.com/course",
        instructor="Ada Lovelace",
        lessons=[
            Lesson(lesson_number=0, title="Introduction", lesson_link="https://example.com/l0"),
            Lesson(lesson_number=1, title="Advanced Widgets", lesson_link="https://example.com/l1"),
        ],
    )


@pytest.fixture
def sample_chunks(sample_course):
    return [
        CourseChunk(
            content="Widgets are small mechanical devices used to demonstrate rotation and torque in this course.",
            course_title=sample_course.title,
            lesson_number=0,
            chunk_index=0,
        ),
        CourseChunk(
            content="This introduction covers what a widget is and why engineers study widget assembly.",
            course_title=sample_course.title,
            lesson_number=0,
            chunk_index=1,
        ),
        CourseChunk(
            content="Advanced widgets rotate on a central axle and can spin at high speed when calibrated correctly.",
            course_title=sample_course.title,
            lesson_number=1,
            chunk_index=2,
        ),
        CourseChunk(
            content="Calibrating widget rotation speed requires adjusting the torque spring tension carefully.",
            course_title=sample_course.title,
            lesson_number=1,
            chunk_index=3,
        ),
    ]


@pytest.fixture
def vector_store(tmp_chroma_path, sample_course, sample_chunks):
    store = VectorStore(tmp_chroma_path, "all-MiniLM-L6-v2", max_results=5)
    store.add_course_metadata(sample_course)
    store.add_course_content(sample_chunks)
    return store


@pytest.fixture
def course_search_tool(vector_store):
    return CourseSearchTool(vector_store)


@pytest.fixture
def tool_manager(vector_store):
    manager = ToolManager()
    manager.register_tool(CourseSearchTool(vector_store))
    manager.register_tool(CourseListTool(vector_store))
    manager.register_tool(CourseOutlineTool(vector_store))
    return manager


@pytest.fixture
def fake_config(tmp_chroma_path):
    return SimpleNamespace(
        CHROMA_PATH=tmp_chroma_path,
        EMBEDDING_MODEL="all-MiniLM-L6-v2",
        MAX_RESULTS=5,
        ANTHROPIC_API_KEY="test-key-not-real",
        ANTHROPIC_MODEL="claude-sonnet-5",
        MAX_HISTORY=2,
        CHUNK_SIZE=800,
        CHUNK_OVERLAP=100,
    )


def make_text_block(text):
    return SimpleNamespace(type="text", text=text)


def make_tool_use_block(name, input, id="toolu_1"):
    return SimpleNamespace(type="tool_use", name=name, input=input, id=id)


def make_response(stop_reason, content):
    return SimpleNamespace(stop_reason=stop_reason, content=content)


@pytest.fixture
def response_factory():
    return SimpleNamespace(
        text_block=make_text_block,
        tool_use_block=make_tool_use_block,
        response=make_response,
    )
