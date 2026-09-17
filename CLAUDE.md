# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

Package manager is `uv` (not pip/poetry). Python >= 3.13 required. Always use `uv run ...` to run any Python file/script and `uv sync`/`uv add` to manage dependencies — never invoke `python`/`pip` directly.

```bash
# Install dependencies
uv sync

# Run the app (from repo root) — starts backend on :8000, serves frontend too
./run.sh
# or manually:
cd backend && uv run uvicorn app:app --reload --port 8000
```

- Web UI: http://localhost:8000
- API docs (Swagger): http://localhost:8000/docs
- Requires a `.env` file in the repo root with `ANTHROPIC_API_KEY=...` (see `.env.example`)

There is no test suite, linter, or formatter configured in this repo currently.

## Architecture

This is a RAG chatbot that answers questions about course transcripts stored in `docs/`. Backend is FastAPI (`backend/`), frontend is vanilla JS/HTML/CSS (`frontend/`), served as static files by the same FastAPI app (`app.py` mounts `../frontend` at `/`).

### Request flow

`frontend/script.js` → `POST /api/query` → `RAGSystem.query()` (`backend/rag_system.py`) → `AIGenerator.generate_response()` (`backend/ai_generator.py`), which calls Claude with all registered tools available (`search_course_content`, `get_course_list`, `get_course_outline`). Claude decides whether/which tool(s) to call (system prompt: only for course-specific questions). Tool calling is **sequential across up to `AIGenerator.MAX_TOOL_ROUNDS` (2) rounds** — each tool call is its own API round-trip, so Claude can see one tool's results before deciding whether to make another (e.g. look up a course outline, then search for content on a topic found in it). Each round, `AIGenerator` executes the requested tool call(s) through `ToolManager` → the tool's `execute()` (`backend/search_tools.py`) → `VectorStore` (`backend/vector_store.py`), and feeds results back to Claude. Once the round cap is reached (or a tool call raises — an in-band error string like "no results found" is not a failure, only a Python exception is), a final tools-omitted API call forces Claude to synthesize a text answer from whatever was gathered. Sources used in the answer are tracked on the tool instance (`CourseSearchTool.last_sources`, accumulated across rounds rather than overwritten so multi-search/comparison queries keep every round's sources) and returned alongside the answer to the frontend for citation display, then reset via `ToolManager.reset_sources()`.

Key point: retrieval is **agentic**, not a fixed pipeline — Claude itself decides whether/what to search via Anthropic tool-calling, rather than the backend always doing a vector search before calling the LLM.

### Vector storage (ChromaDB)

`VectorStore` (`backend/vector_store.py`) maintains two collections:
- `course_catalog` — one entry per course (title as ID), with instructor, course link, and lessons serialized as JSON in metadata. Used to semantically resolve fuzzy/partial course names (e.g. "MCP" → full title) before filtering content search.
- `course_content` — chunked lesson text with `course_title`/`lesson_number`/`chunk_index` metadata, used for the actual semantic search.

A search first resolves `course_name` (if given) to an exact title via a semantic query against `course_catalog`, then queries `course_content` filtered by that resolved title and/or `lesson_number`.

### Document ingestion format

`DocumentProcessor` (`backend/document_processor.py`) expects course `.txt` files shaped like:
```
Course Title: ...
Course Link: ...
Course Instructor: ...

Lesson 0: Introduction
Lesson Link: ...
<lesson content...>

Lesson 1: ...
<lesson content...>
```
Text is chunked sentence-aware with overlap (`CHUNK_SIZE`/`CHUNK_OVERLAP` in `config.py`), and each chunk is prefixed with course/lesson context to improve standalone retrievability. On startup, `app.py` auto-loads all files from `../docs` into the vector store (skips courses whose title already exists — id'd by course title, so re-running does not duplicate).

### Session/history

`SessionManager` (`backend/session_manager.py`) is in-memory only (lost on restart), keyed by generated `session_{n}` IDs, capped at `MAX_HISTORY` exchanges (`config.py`). History is formatted as plain text and injected into the system prompt for follow-up context, not passed as multi-turn message history to the Anthropic API.

### Config

All tunables live in `backend/config.py` (loaded via `.env` + `python-dotenv`): `ANTHROPIC_MODEL`, `EMBEDDING_MODEL` (`all-MiniLM-L6-v2` via sentence-transformers), `CHUNK_SIZE`/`CHUNK_OVERLAP`, `MAX_RESULTS` (search results), `MAX_HISTORY`, `CHROMA_PATH`.

### Adding a new tool

Tools implement the `Tool` ABC in `backend/search_tools.py` (`get_tool_definition()` + `execute()`) and are registered on `ToolManager` in `RAGSystem.__init__` (`backend/rag_system.py`). `ToolManager` handles dispatch by tool name and aggregates `last_sources` from any tool exposing that attribute — follow this convention so citations keep working.
