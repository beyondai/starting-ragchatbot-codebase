# Changes: code quality tooling

Note: this feature was requested via the `/implement-feature` command, which is
scoped to front-end features. The work here is developer tooling for the Python
backend, not the front-end; no files under `frontend/` were touched. The change
log is still recorded here because the command requires it.

## Summary

Added black (formatter), isort (import sorter) and flake8 (linter) to the
development workflow, formatted the whole Python codebase with them, and added
shell scripts to run the checks.

## Dependencies (`pyproject.toml`, `uv.lock`)

Added to the `dev` dependency group (installed by `uv sync`):

- `black>=25.1,<26` (locked 25.12.0)
- `isort>=6.0,<7` (locked 6.1.0)
- `flake8>=7.1,<8` (locked 7.3.0)

## Configuration

- `pyproject.toml`
  - `[tool.black]`: line length 88, target `py313`, excludes `.venv`, `.trees`,
    `backend/chroma_db`.
  - `[tool.isort]`: `profile = "black"`, line length 88, `src_paths` set to
    `backend` so local modules are classified as first-party,
    `skip_gitignore = true`.
- `.flake8` (new; flake8 does not read `pyproject.toml`)
  - max line length 88; ignores E203, E501, W503 so it never fights black.
  - `per-file-ignores` for E402 in `backend/app.py` (warnings filter must run
    before the heavy imports it silences) and `backend/tests/conftest.py`
    (`sys.path` is patched before backend modules are importable).

## Scripts (`scripts/`, new, all executable)

- `scripts/format.sh` - runs `isort` then `black` in place. Defaults to
  `backend` and `main.py`; accepts paths as arguments.
- `scripts/lint.sh` - runs `isort --check-only --diff`, `black --check --diff`,
  and `flake8`. Does not modify files; runs all three and exits non-zero if
  any fail.
- `scripts/check.sh` - runs `lint.sh` then `uv run pytest` (extra args are
  passed to pytest). Intended as the pre-commit / pre-PR gate.

All scripts `cd` to the repo root and invoke tools via `uv run`.

## Codebase formatting

Ran `isort` and `black` across `backend/` and `main.py`: 14 files reformatted
(quote normalisation, trailing commas, argument wrapping, blank-line spacing,
sorted/grouped imports). No logic changes.

Two files have imports that must stay below setup code, so a `# isort: split`
marker was added to stop isort hoisting them:

- `backend/app.py` - `warnings.filterwarnings(...)` before the fastapi/rag imports.
- `backend/tests/conftest.py` - `sys.path.insert(...)` before backend imports.

## flake8 fixes

Small, behaviour-preserving fixes so the lint gate passes cleanly:

- `backend/app.py`: removed a duplicated mid-file `import os` /
  `from fastapi.staticfiles import StaticFiles` and an unused
  `from pathlib import Path`; moved `from fastapi.responses import FileResponse`
  to the top-level import block.
- `backend/models.py`: removed unused `Dict` import.
- `backend/rag_system.py`: removed unused `CourseChunk`, `Lesson` imports.
- `backend/search_tools.py`: removed unused `Protocol` import.
- `backend/vector_store.py`: removed unused `SentenceTransformer` import;
  renamed lambda parameter `l` to `lesson` (E741).

## Docs

- `CLAUDE.md`: replaced the outdated "no test suite, linter, or formatter" line
  with a "Tests and code quality" section describing the scripts and the
  black/isort/flake8 conventions.
- `README.md`: added a "Development" section listing the three scripts.

## Verification

- `isort --check-only`, `black --check`, and `flake8` all pass on `backend/`
  and `main.py` (run with the locked tool versions).
- `python -m compileall backend main.py` succeeds.
- The pytest suite could not be run on the authoring machine: `torch` (pulled in
  by `sentence-transformers`) has no wheel for macOS x86_64, so `uv sync` fails
  there. The reformat was reviewed with `git diff -w` and contains only
  black-style rewrapping plus the import removals listed above. Run
  `./scripts/check.sh` on a supported platform to confirm.
