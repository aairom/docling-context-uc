#!/usr/bin/env bash
# End-to-end CLI demo: load samples, ingest, search, ask; reports land in output/.
# Usage: scripts/demo.sh
source "$(dirname "$0")/_common.sh"
ensure_env
"$(dirname "$0")/load-samples.sh"
cd "${ROOT_DIR}"
uv run --no-sync dcuc demo
echo
uv run --no-sync dcuc tree
