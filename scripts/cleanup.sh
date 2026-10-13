#!/usr/bin/env bash
# End-of-project clean-up: stop the app and delete .venv, node_modules, __pycache__ and caches.
# Data (context-data/), input/ and output/ are kept unless --all is given.
# Usage: scripts/cleanup.sh [--all]
source "$(dirname "$0")/_common.sh"

"$(dirname "$0")/stop.sh" || true
cd "${ROOT_DIR}"

find . -type d \( -name node_modules -o -name .venv -o -name __pycache__ \
  -o -name .pytest_cache -o -name .ruff_cache -o -name .gradio \) -prune \
  -exec rm -rf {} + 2>/dev/null || true
rm -rf .coverage htmlcov .run logs

if [[ "${1:-}" == "--all" ]]; then
  rm -rf context-data
  find input output -mindepth 1 ! -name .gitkeep -exec rm -rf {} + 2>/dev/null || true
  echo "Removed runtime data, input/ and output/ contents."
fi
echo "Clean-up complete."
