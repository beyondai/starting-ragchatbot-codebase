#!/bin/bash
# Full quality gate: lint (isort/black/flake8) then the pytest suite.
# Run this before committing or opening a PR.
set -euo pipefail
cd "$(dirname "$0")/.."

./scripts/lint.sh

echo "==> pytest"
uv run pytest "$@"

echo
echo "All quality checks passed."
