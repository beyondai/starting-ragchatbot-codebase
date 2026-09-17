"""Bug-hunting integration tests using real ingested course data, to
diagnose why content-related queries return a failure in the running app.
"""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from document_processor import DocumentProcessor
from search_tools import CourseSearchTool
from rag_system import RAGSystem

REPO_ROOT = Path(__file__).resolve().parents[2]
COURSE1_PATH = REPO_ROOT / "docs" / "course1_script.txt"
DOCS_DIR = REPO_ROOT / "docs"


@pytest.fixture
def real_ingested_vector_store(tmp_chroma_path):
    from vector_store import VectorStore

    store = VectorStore(tmp_chroma_path, "all-MiniLM-L6-v2", max_results=5)
    processor = DocumentProcessor(chunk_size=800, chunk_overlap=100)
    course, chunks = processor.process_course_document(str(COURSE1_PATH))
    store.add_course_metadata(course)
    store.add_course_content(chunks)
    return store, course


@pytest.fixture
def all_real_courses_vector_store(tmp_chroma_path):
    """Ingests all 4 real docs/ courses - used to regression-test
    VectorStore._resolve_course_name's false-positive fix across multiple
    real, semantically-related-but-distinct course titles (a single-course
    fixture can't exercise cross-course confusion)."""
    from vector_store import VectorStore

    store = VectorStore(tmp_chroma_path, "all-MiniLM-L6-v2", max_results=5)
    processor = DocumentProcessor(chunk_size=800, chunk_overlap=100)
    for doc_path in sorted(DOCS_DIR.glob("*.txt")):
        course, chunks = processor.process_course_document(str(doc_path))
        store.add_course_metadata(course)
        store.add_course_content(chunks)
    return store


def test_real_document_processing_produces_searchable_chunks(real_ingested_vector_store):
    store, _course = real_ingested_vector_store

    results = store.search(query="computer use")

    assert results.error is None
    assert not results.is_empty()


def test_real_document_processing_course_search_tool_end_to_end(real_ingested_vector_store):
    store, course = real_ingested_vector_store
    tool = CourseSearchTool(store)

    result = tool.execute(query="computer use with Anthropic")

    assert f"[{course.title}" in result
    assert tool.last_sources


def test_resolve_course_name_rejects_semantically_nearby_wrong_topic(all_real_courses_vector_store):
    """Regression test for the fixed VectorStore._resolve_course_name bug.

    'Deep Learning Specialization' empirically has a *smaller* embedding
    distance to a real course title than some genuine partial-title matches
    do (see the investigation that led to this fix), so a naive distance
    threshold can't separate it - only the combined distance+lexical check
    correctly rejects it.
    """
    store = all_real_courses_vector_store

    assert store._resolve_course_name("Deep Learning Specialization") is None
    assert store._resolve_course_name("Introduction to Python Programming") is None
    assert store._resolve_course_name("The Great Gatsby") is None


def test_resolve_course_name_still_matches_real_partial_titles(all_real_courses_vector_store):
    store = all_real_courses_vector_store

    assert store._resolve_course_name("MCP") == "MCP: Build Rich-Context AI Apps with Anthropic"
    assert store._resolve_course_name("Chroma") == "Advanced Retrieval for AI with Chroma"
    assert store._resolve_course_name("computer use") == "Building Towards Computer Use with Anthropic"
    assert store._resolve_course_name("Prompt Compression") == "Prompt Compression and Query Optimization"


@pytest.mark.live
def test_real_pipeline_with_live_anthropic_call(tmp_chroma_path):
    """Opt-in only: exercises the real, unmocked Anthropic API against the
    real ingested course data. Run manually with a valid ANTHROPIC_API_KEY:

        uv run pytest backend/tests/test_diagnostic_full_path.py -v -m live

    Interpreting failures:
    - NotFoundError/BadRequestError mentioning "model" -> invalid ANTHROPIC_MODEL.
    - AuthenticationError -> the checked-in .env key is dead, rotate it.
    - Fallback string returned, no exception, but sources non-empty ->
      a tool ran fine but the answer still got swallowed - see
      AIGenerator._run_tool_loop/_response_to_text for where that path lives.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        pytest.skip("ANTHROPIC_API_KEY not set")

    config = SimpleNamespace(
        CHROMA_PATH=tmp_chroma_path,
        EMBEDDING_MODEL="all-MiniLM-L6-v2",
        MAX_RESULTS=5,
        ANTHROPIC_API_KEY=api_key,
        ANTHROPIC_MODEL="claude-sonnet-5",
        MAX_HISTORY=2,
        CHUNK_SIZE=800,
        CHUNK_OVERLAP=100,
    )
    rag_system = RAGSystem(config)
    processor = DocumentProcessor(chunk_size=800, chunk_overlap=100)
    course, chunks = processor.process_course_document(str(COURSE1_PATH))
    rag_system.vector_store.add_course_metadata(course)
    rag_system.vector_store.add_course_content(chunks)

    response, sources = rag_system.query("What is computer use, according to the course?")

    print(f"\nLIVE DIAGNOSTIC RESULT:\nresponse={response!r}\nsources={sources!r}")
    assert response
    assert response != "I wasn't able to generate a response for that question — please try asking again."
