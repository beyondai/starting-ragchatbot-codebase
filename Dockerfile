# Base image: official Python 3.13 on slim Debian Linux.
# This is the key fix — Linux wheels for torch/sentence-transformers exist
# for Python 3.13; it's only macOS x86_64 that Torch stopped supporting.
FROM python:3.13-slim

# Install uv by copying its binary from Astral's official image — no need
# to run the curl installer script inside the container.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# All subsequent instructions run from /app inside the container.
WORKDIR /app

# Copy dependency manifests first, install, THEN copy the rest of the code.
# Docker caches each instruction as a layer; as long as pyproject.toml/uv.lock
# don't change, this expensive install step is reused from cache on rebuilds
# instead of re-running — so editing app code doesn't reinstall torch etc.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-install-project

# Now copy the actual application: backend code, frontend static files, and
# the course documents the app loads on startup.
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY docs/ ./docs/

# Purely documentation — tells humans/tools which port the app listens on.
# It does NOT actually publish the port; that happens with `docker run -p`.
EXPOSE 8000

# The command that runs when a container starts. Matches run.sh's manual
# start command, minus --reload (that's a dev-only convenience).
WORKDIR /app/backend
CMD ["uv", "run", "uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
