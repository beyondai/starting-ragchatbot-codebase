"""Tests for the FastAPI endpoints mirrored from backend/app.py.

Runs against create_test_app() (conftest.py) with a mocked RAGSystem, so
these cover request validation, response shapes, session handling and
error mapping, not retrieval or generation.
"""
import pytest

pytestmark = pytest.mark.api


# --- POST /api/query -------------------------------------------------------

def test_query_returns_answer_sources_and_session(client, mock_rag_system):
    resp = client.post("/api/query", json={"query": "Tell me about widget rotation"})

    assert resp.status_code == 200
    body = resp.json()
    assert set(body.keys()) == {"answer", "sources", "session_id"}
    assert body["answer"] == "Widgets rotate on an axle."
    assert body["sources"] == [
        {"text": "Test Course: Intro to Widgets - Lesson 1", "link": "https://example.com/l1"},
        {"text": "Test Course: Intro to Widgets - Lesson 0", "link": None},
    ]
    assert body["session_id"] == "session_1"


def test_query_creates_session_when_none_provided(client, mock_rag_system):
    resp = client.post("/api/query", json={"query": "hello"})

    session_id = resp.json()["session_id"]
    assert session_id in mock_rag_system.session_manager.sessions
    mock_rag_system.query.assert_called_once_with("hello", session_id)


def test_query_reuses_provided_session_id(client, mock_rag_system):
    resp = client.post("/api/query", json={"query": "follow-up", "session_id": "session_42"})

    assert resp.status_code == 200
    assert resp.json()["session_id"] == "session_42"
    mock_rag_system.query.assert_called_once_with("follow-up", "session_42")
    # No new session should be minted when the client supplied one
    assert mock_rag_system.session_manager.session_counter == 0


def test_query_treats_empty_session_id_as_missing(client, mock_rag_system):
    resp = client.post("/api/query", json={"query": "hello", "session_id": ""})

    assert resp.status_code == 200
    assert resp.json()["session_id"] == "session_1"


def test_query_with_no_sources(client, mock_rag_system):
    mock_rag_system.query.return_value = ("The sky is blue.", [])

    resp = client.post("/api/query", json={"query": "Why is the sky blue?"})

    assert resp.status_code == 200
    assert resp.json()["sources"] == []


def test_query_missing_query_field_is_422(client, mock_rag_system):
    resp = client.post("/api/query", json={"session_id": "session_1"})

    assert resp.status_code == 422
    mock_rag_system.query.assert_not_called()


def test_query_wrong_query_type_is_422(client, mock_rag_system):
    resp = client.post("/api/query", json={"query": ["not", "a", "string"]})

    assert resp.status_code == 422
    mock_rag_system.query.assert_not_called()


def test_query_non_json_body_is_422(client):
    resp = client.post("/api/query", content="query=hello",
                       headers={"Content-Type": "text/plain"})

    assert resp.status_code == 422


def test_query_rag_failure_maps_to_500_with_detail(client, mock_rag_system):
    mock_rag_system.query.side_effect = RuntimeError("anthropic is down")

    resp = client.post("/api/query", json={"query": "anything"})

    assert resp.status_code == 500
    assert resp.json() == {"detail": "anthropic is down"}


def test_query_malformed_sources_from_rag_is_500(client, mock_rag_system):
    # A source missing the required "text" key fails response validation;
    # the endpoint's catch-all turns that into a 500 rather than a crash.
    mock_rag_system.query.return_value = ("answer", [{"link": "https://example.com"}])

    resp = client.post("/api/query", json={"query": "anything"})

    assert resp.status_code == 500


# --- DELETE /api/session/{session_id} ---------------------------------------

def test_delete_session_removes_history(client, mock_rag_system):
    sm = mock_rag_system.session_manager
    sid = sm.create_session()
    sm.add_exchange(sid, "q", "a")

    resp = client.delete(f"/api/session/{sid}")

    assert resp.status_code == 200
    assert resp.json() == {"success": True}
    assert sid not in sm.sessions


def test_delete_unknown_session_is_still_success(client):
    resp = client.delete("/api/session/never_existed")

    assert resp.status_code == 200
    assert resp.json() == {"success": True}


# --- GET /api/courses --------------------------------------------------------

def test_courses_returns_stats(client, mock_rag_system):
    resp = client.get("/api/courses")

    assert resp.status_code == 200
    assert resp.json() == {
        "total_courses": 2,
        "course_titles": ["Test Course: Intro to Widgets", "Another Course"],
    }
    mock_rag_system.get_course_analytics.assert_called_once_with()


def test_courses_empty_catalog(client, mock_rag_system):
    mock_rag_system.get_course_analytics.return_value = {"total_courses": 0, "course_titles": []}

    resp = client.get("/api/courses")

    assert resp.status_code == 200
    assert resp.json() == {"total_courses": 0, "course_titles": []}


def test_courses_failure_maps_to_500(client, mock_rag_system):
    mock_rag_system.get_course_analytics.side_effect = Exception("chroma unavailable")

    resp = client.get("/api/courses")

    assert resp.status_code == 500
    assert resp.json() == {"detail": "chroma unavailable"}


def test_courses_rejects_post(client):
    resp = client.post("/api/courses")

    assert resp.status_code == 405


# --- GET / (static frontend) ------------------------------------------------

def test_root_serves_frontend_index(client):
    resp = client.get("/")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    assert "Test Frontend" in resp.text


def test_root_serves_other_static_assets(client):
    resp = client.get("/script.js")

    assert resp.status_code == 200
    assert "stub" in resp.text


def test_unknown_static_path_is_404(client):
    resp = client.get("/does-not-exist.html")

    assert resp.status_code == 404


def test_api_routes_take_precedence_over_static_mount(client):
    # The catch-all "/" mount must not shadow /api/* routes
    resp = client.get("/api/courses")

    assert resp.status_code == 200
    assert "total_courses" in resp.json()


def test_app_without_frontend_dir_has_no_static_root(mock_rag_system):
    from fastapi.testclient import TestClient
    from conftest import create_test_app

    with TestClient(create_test_app(mock_rag_system)) as c:
        assert c.get("/").status_code == 404
        assert c.get("/api/courses").status_code == 200
