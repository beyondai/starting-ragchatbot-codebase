# Frontend changes: theme toggle button

Adds a dark/light theme toggle button to the top-right of the app. Clicking (or pressing Enter/Space on) the button switches between the existing dark theme and a new light theme, animates the sun/moon icon swap, and remembers the choice across reloads.

## `frontend/index.html`

- Added `<button id="themeToggle" class="theme-toggle">` as the first child of `<body>`, containing two inline SVG icons (`.theme-icon-sun` and `.theme-icon-moon`, both `aria-hidden="true"`). The button carries `type="button"`, `aria-label`, `aria-pressed`, and `title` so screen readers announce it as a toggle with its current state.
- Added a tiny inline `<script>` in `<head>` that reads `localStorage.theme` and sets `data-theme="light"` on `<html>` before first paint, so a saved light theme does not flash dark on load.
- Bumped cache-buster query strings: `style.css?v=11`, `script.js?v=10`.

## `frontend/style.css`

- Added `--code-bg` variable to `:root` and replaced the hardcoded `rgba(0,0,0,0.2)` on `.message-content code` / `.message-content pre` with it.
- Added a `[data-theme="light"]` block that overrides the palette variables (background, surface, text, border, shadow, welcome, code-bg). The dark theme remains the default on bare `:root`, so nothing changes for existing users until they toggle.
- Added `.theme-toggle` styles: `position: fixed; top: 1rem; right: 1rem`, 44x44 circular button using `--surface` / `--border-color` / `--shadow`, hover lifts and tints to `--primary-color`, `:active` scales down slightly, `:focus-visible` shows the same `--focus-ring` used by the input and send button (mouse clicks do not leave a ring).
- Added `.theme-icon` animation: both icons are absolutely stacked; the inactive one is faded out and rotated/scaled down, and the swap uses a 0.3s opacity fade plus a 0.4s springy rotate/scale transition.
- Added 0.3s `background-color` / `color` / `border-color` transitions on `body`, `.sidebar`, and `.chat-input-container` so the theme change crossfades rather than snapping.
- Added a `prefers-reduced-motion: reduce` rule that disables those transitions.

## `frontend/script.js`

- Added `themeToggle` to the DOM element globals and a `THEME_STORAGE_KEY` constant.
- Added theme helpers: `getSavedTheme()` (reads localStorage, defaults to `dark`), `getCurrentTheme()`, `applyTheme(theme)` (sets/removes `data-theme` on `<html>`), `updateThemeToggle(theme)` (syncs `aria-pressed` and `aria-label`), and `toggleTheme()` (flips theme, updates ARIA, persists to localStorage).
- `applyTheme(getSavedTheme())` runs at script load as a fallback to the head script; `updateThemeToggle()` runs on `DOMContentLoaded` so the button's ARIA state matches the restored theme.
- Registered `themeToggle.addEventListener('click', toggleTheme)` in `setupEventListeners()`. Because it is a native `<button>`, Tab focuses it and Enter/Space trigger the click without extra key handlers.

## Verification

Served `frontend/` statically and drove it with Playwright:
- Dark theme renders with the sun icon top-right; clicking switches to the light palette with the moon icon.
- Enter on the focused button toggles back to dark and focus stays on the button.
- `aria-pressed` and `aria-label` update on every toggle; `localStorage.theme` is written.
- Reloading restores the saved light theme with `aria-pressed="true"`.

---

# Frontend changes: complete light theme palette

Builds on the toggle above: the `[data-theme="light"]` block is now a full palette rather than a partial override, every remaining hardcoded color in the stylesheet is tokenized so it adapts per theme, and all pairs were checked against WCAG.

## `frontend/style.css`

### New tokens on `:root` (dark defaults)
- `--input-border` (#475569) - boundary for form controls (`#chatInput`, `.theme-toggle`); slightly stronger than the decorative `--border-color`.
- `--welcome-shadow`, `--primary-glow` - replace hardcoded shadows on the welcome bubble and send-button hover.
- `--error-bg` / `--error-text` / `--error-border` and `--success-bg` / `--success-text` / `--success-border` - replace hardcoded reds/greens in `.error-message` and `.success-message`. Dark values are identical to the previous hardcoded ones, so dark mode is visually unchanged.

### Light palette (`[data-theme="light"]`)
| Token | Value | Notes |
|---|---|---|
| `--primary-color` | `#1d4ed8` | darker than dark-mode `#2563eb` so accent text hits 6.7:1 on white |
| `--primary-hover` | `#1e40af` | |
| `--background` | `#f8fafc` | page / chat area |
| `--surface` | `#ffffff` | sidebar, bubbles, input |
| `--surface-hover` | `#e2e8f0` | |
| `--text-primary` | `#0f172a` | 17.9:1 on surface |
| `--text-secondary` | `#475569` | 7.6:1 on surface, 7.2:1 on background |
| `--border-color` | `#cbd5e1` | decorative separators / cards |
| `--input-border` | `#8592a6` | 3.1:1 on white, meets WCAG 1.4.11 non-text contrast |
| `--user-message` | `#1d4ed8` | white text = 6.7:1 |
| `--focus-ring` | `rgba(29,78,216,.25)` | |
| `--welcome-bg` / `--welcome-border` | `#dbeafe` / `#1d4ed8` | |
| `--code-bg` | `rgba(15,23,42,.06)` | |
| `--shadow` / `--welcome-shadow` / `--primary-glow` | lighter, slate-tinted | |
| `--error-*` | `#fef2f2` / `#b91c1c` / `#fecaca` | 5.9:1 |
| `--success-*` | `#f0fdf4` / `#15803d` / `#bbf7d0` | 4.8:1 |

The ratios are also recorded in a comment above the block in the stylesheet.

### Other fixes
- `.message-content blockquote` referenced an undefined `var(--primary)`; changed to `var(--primary-color)` so the left rule actually renders (both themes).
- `.source-link` underline color, welcome-bubble shadow, send-button hover glow, error/success banners now use tokens instead of literal rgba values.
- The only remaining literal color is the gradient on `header h1`, which is `display: none`.

## `frontend/index.html`
- Cache-buster bumped to `style.css?v=12`.

## `frontend/script.js`
- No changes needed; the toggle logic from the previous feature (click handler, `data-theme` on `<html>`, localStorage persistence, ARIA sync) drives this palette.

## Verification
- Computed WCAG contrast for every foreground/background pair with a small script: all text pairs pass AA (most AAA); control borders pass the 3:1 non-text threshold.
- Rendered both themes in Playwright with a user message, a markdown assistant reply (bold, list, inline code, blockquote, code block), an expanded sources list, error and success banners, and expanded sidebar sections. Light mode reads cleanly; dark mode is visually unchanged apart from the now-visible blockquote rule.

---

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
