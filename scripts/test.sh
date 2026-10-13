#!/usr/bin/env bash
# Run lint + the unit/integration test suite with coverage.
# Usage: scripts/test.sh [extra pytest args]
source "$(dirname "$0")/_common.sh"
require_uv
cd "${ROOT_DIR}"
uv sync --quiet
uv run --no-sync ruff check dcuc tests app.py
uv run --no-sync pytest --cov=dcuc --cov=app --cov-report=term-missing "$@"
