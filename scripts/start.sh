#!/usr/bin/env bash
# Start the web UI in detached mode and print its URL.
# Usage: scripts/start.sh
source "$(dirname "$0")/_common.sh"

if is_running; then
  echo "Already running (pid $(cat "${PID_FILE}"))."
else
  ensure_env
  mkdir -p "${RUN_DIR}" "${LOG_DIR}" "${ROOT_DIR}/input" "${ROOT_DIR}/output"
  cd "${ROOT_DIR}"
  # nohup + background + own PID file = detached; logs go to logs/app.log.
  nohup uv run --no-sync python app.py >>"${LOG_FILE}" 2>&1 &
  echo $! >"${PID_FILE}"
fi

HOST="$(env_value APP_HOST 127.0.0.1)"
PORT="$(env_value APP_PORT 7860)"
URL="http://${HOST}:${PORT}"

# Wait (max ~60s) until the server answers so the printed URL is usable.
for _ in $(seq 1 60); do
  if curl -fsS -o /dev/null "${URL}" 2>/dev/null; then
    echo "docling-context sample is running: ${URL}"
    echo "Logs: ${LOG_FILE}   Stop: scripts/stop.sh"
    exit 0
  fi
  if ! is_running; then
    echo "The application exited during start-up. Last log lines:" >&2
    tail -n 20 "${LOG_FILE}" >&2
    rm -f "${PID_FILE}"
    exit 1
  fi
  sleep 1
done
echo "Started (pid $(cat "${PID_FILE}")) but ${URL} is not answering yet; see ${LOG_FILE}" >&2
exit 1
