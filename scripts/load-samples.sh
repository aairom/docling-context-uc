#!/usr/bin/env bash
# Copy the bundled sample documents into input/ (never overwrites existing files).
# Usage: scripts/load-samples.sh
source "$(dirname "$0")/_common.sh"
mkdir -p "${ROOT_DIR}/input"
# rsync --ignore-existing: copy new files only; portable exit status (unlike macOS `cp -n`).
rsync -a --ignore-existing "${ROOT_DIR}/samples/" "${ROOT_DIR}/input/"
echo "Sample documents are in ${ROOT_DIR}/input:"
find "${ROOT_DIR}/input" -type f ! -name .gitkeep | sed "s|${ROOT_DIR}/||" | sort
