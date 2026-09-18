# Feature: API testing infrastructure

Note: this feature is backend test infrastructure, not a front-end change. No files under `frontend/` were modified. It is recorded here because the `/implement-feature` command writes its summary to this file.

## What changed

### `backend/tests/conftest.py`
- Added `create_test_app(rag_system, frontend_dir=None)`: a FastAPI app that mirrors the routes and Pydantic models of `backend/app.py` (`POST /api/query`, `DELETE /api/session/{id}`, `GET /api/courses`, static mount at `/`) but takes the `RAGSystem` as an argument and only mounts static files when given an explicit directory. This avoids importing `app.py`, which builds a real `RAGSystem` against `./chroma_db` and mounts `../frontend` relative to CWD at import time.
- New fixtures:
  - `mock_rag_system`: `MagicMock` with a real in-memory `SessionManager` and canned `query()` / `get_course_analytics()` results.
  - `frontend_dir`: a `tmp_path` stub frontend (`index.html`, `script.js`) so `/` can be exercised without the real frontend.
  - `test_app` / `client`: the test app and a `fastapi.testclient.TestClient` bound to it.

### `backend/tests/test_api_endpoints.py` (new, 21 tests, marked `api`)
- `/api/query`: response shape, session creation when `session_id` is missing or empty, reuse of a provided `session_id`, empty sources, 422 on missing/invalid body, 500 with `detail` when `RAGSystem.query` raises or returns malformed sources.
- `/api/session/{id}`: deletes history, succeeds for unknown ids.
- `/api/courses`: stats payload, empty catalog, 500 on failure, 405 on POST.
- `/`: serves `index.html` and other static assets, 404 on unknown paths, API routes are not shadowed by the static mount, app without a frontend dir has no static root.

### `pyproject.toml`
- Registered the `api` pytest marker (`uv run pytest -m api`).
- Added `httpx` to the `dev` dependency group (required by `TestClient`; previously only present transitively). `uv.lock` updated via `uv add`.

### `CLAUDE.md`
- Replaced the stale "there is no test suite" line with how to run the tests, the `create_test_app()` convention, and the Docker command for macOS x86_64 hosts.

## Verification
Run inside the project Docker image (torch has no macOS x86_64 wheel, so `uv sync` fails natively here):

```
docker run --rm -v "$PWD:/app" -v starting-ragchatbot-codebase_venv:/app/.venv -w /app \
  starting-ragchatbot-codebase-app:latest uv run --no-sync pytest -q
56 passed, 1 deselected in 42.59s
```
