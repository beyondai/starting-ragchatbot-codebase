#!/bin/bash
# Auto-format the Python codebase in place (isort -> black).
# Usage: ./scripts/format.sh [paths...]   (defaults to backend/ and main.py)
set -euo pipefail
cd "$(dirname "$0")/.."

TARGETS=("$@")
if [ ${#TARGETS[@]} -eq 0 ]; then
    TARGETS=(backend main.py)
fi

echo "==> isort"
uv run isort "${TARGETS[@]}"
echo "==> black"
uv run black "${TARGETS[@]}"
echo "Formatting complete."
