#!/usr/bin/env bash
# Gracefully stop the web UI: SIGTERM first (the app closes the store), SIGKILL after a timeout.
# Usage: scripts/stop.sh
source "$(dirname "$0")/_common.sh"

if ! is_running; then
  echo "Not running."
  rm -f "${PID_FILE}"
  exit 0
fi

PID="$(cat "${PID_FILE}")"
# `uv run` spawns python as a child; signal the whole process group of children too.
CHILDREN="$(pgrep -P "${PID}" || true)"
echo "Stopping pid ${PID} ${CHILDREN} ..."
kill -TERM ${CHILDREN} "${PID}" 2>/dev/null || true

for _ in $(seq 1 15); do
  if ! kill -0 "${PID}" 2>/dev/null; then
    rm -f "${PID_FILE}"
    echo "Stopped gracefully."
    exit 0
  fi
  sleep 1
done

echo "Did not stop within 15s; forcing." >&2
kill -KILL ${CHILDREN} "${PID}" 2>/dev/null || true
rm -f "${PID_FILE}"
