#!/bin/bash
# Check formatting and lint without modifying files. Exits non-zero on any issue.
# Usage: ./scripts/lint.sh [paths...]   (defaults to backend/ and main.py)
set -uo pipefail
cd "$(dirname "$0")/.."

TARGETS=("$@")
if [ ${#TARGETS[@]} -eq 0 ]; then
    TARGETS=(backend main.py)
fi

status=0

echo "==> isort --check-only"
uv run isort --check-only --diff "${TARGETS[@]}" || status=1

echo "==> black --check"
uv run black --check --diff "${TARGETS[@]}" || status=1

echo "==> flake8"
uv run flake8 "${TARGETS[@]}" || status=1

if [ $status -ne 0 ]; then
    echo
    echo "Lint failed. Run ./scripts/format.sh to fix formatting issues."
    exit 1
fi
echo "All lint checks passed."
