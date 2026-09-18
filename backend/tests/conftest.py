"""Shared fixtures for the backend test suite.

Never imports backend/app.py: that module constructs a real RAGSystem
against the live ./chroma_db at import time and mounts StaticFiles
relative to CWD. Tests instead build VectorStore/RAGSystem directly
against an isolated tmp_path-based Chroma dir, and API tests run against
a mirror of app.py's endpoints built by create_test_app() below.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from pydantic import BaseModel

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
# isort: split

from models import Course, CourseChunk, Lesson
from search_tools import (
    CourseListTool,
    CourseOutlineTool,
    CourseSearchTool,
    ToolManager,
)
from session_manager import SessionManager
from vector_store import VectorStore


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
            Lesson(
                lesson_number=0,
                title="Introduction",
                lesson_link="https://example.com/l0",
            ),
            Lesson(
                lesson_number=1,
                title="Advanced Widgets",
                lesson_link="https://example.com/l1",
            ),
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


# ---------------------------------------------------------------------------
# API test app
# ---------------------------------------------------------------------------


class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None


class SourceItem(BaseModel):
    text: str
    link: Optional[str] = None


class QueryResponse(BaseModel):
    answer: str
    sources: List[SourceItem]
    session_id: str


class CourseStats(BaseModel):
    total_courses: int
    course_titles: List[str]


def create_test_app(rag_system, frontend_dir: Optional[Path] = None) -> FastAPI:
    """Build a FastAPI app exposing the same routes/models as backend/app.py.

    Mirrors the endpoint bodies in app.py so request validation, response
    shapes, and error mapping are tested, but takes the RAGSystem as an
    argument (so it can be a mock) and only mounts the static frontend when
    given an explicit directory. Keep this in sync with app.py when routes
    change.
    """
    app = FastAPI(title="Course Materials RAG System (test)")

    @app.post("/api/query", response_model=QueryResponse)
    async def query_documents(request: QueryRequest):
        try:
            session_id = request.session_id
            if not session_id:
                session_id = rag_system.session_manager.create_session()
            answer, sources = rag_system.query(request.query, session_id)
            return QueryResponse(answer=answer, sources=sources, session_id=session_id)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.delete("/api/session/{session_id}")
    async def clear_session(session_id: str):
        try:
            rag_system.session_manager.delete_session(session_id)
            return {"success": True}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    @app.get("/api/courses", response_model=CourseStats)
    async def get_course_stats():
        try:
            analytics = rag_system.get_course_analytics()
            return CourseStats(
                total_courses=analytics["total_courses"],
                course_titles=analytics["course_titles"],
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    if frontend_dir is not None:
        app.mount(
            "/", StaticFiles(directory=str(frontend_dir), html=True), name="static"
        )

    return app


@pytest.fixture
def mock_rag_system():
    """A RAGSystem stand-in: real in-memory SessionManager, mocked query/analytics."""
    rag = MagicMock()
    rag.session_manager = SessionManager(max_history=2)
    rag.query.return_value = (
        "Widgets rotate on an axle.",
        [
            {
                "text": "Test Course: Intro to Widgets - Lesson 1",
                "link": "https://example.com/l1",
            },
            {"text": "Test Course: Intro to Widgets - Lesson 0", "link": None},
        ],
    )
    rag.get_course_analytics.return_value = {
        "total_courses": 2,
        "course_titles": ["Test Course: Intro to Widgets", "Another Course"],
    }
    return rag


@pytest.fixture
def frontend_dir(tmp_path):
    """A stub frontend directory so '/' can be served without the real one."""
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<!doctype html><title>Test Frontend</title>")
    (frontend / "script.js").write_text("console.log('stub');")
    return frontend


@pytest.fixture
def test_app(mock_rag_system, frontend_dir):
    return create_test_app(mock_rag_system, frontend_dir=frontend_dir)


@pytest.fixture
def client(test_app):
    with TestClient(test_app) as c:
        yield c
