#!/usr/bin/env bash
# Shared helpers sourced by the other scripts. Not meant to be run directly.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_DIR="${ROOT_DIR}/.run"
LOG_DIR="${ROOT_DIR}/logs"
PID_FILE="${RUN_DIR}/app.pid"
LOG_FILE="${LOG_DIR}/app.log"

# Read a variable from .env (falls back to the given default); never executes .env.
env_value() {
  local name="$1" default="$2" value=""
  if [[ -n "${!name:-}" ]]; then
    printf '%s' "${!name}"; return
  fi
  if [[ -f "${ROOT_DIR}/.env" ]]; then
    value="$(grep -E "^${name}=" "${ROOT_DIR}/.env" | tail -n1 | cut -d= -f2- || true)"
  fi
  printf '%s' "${value:-$default}"
}

require_uv() {
  command -v uv >/dev/null 2>&1 || { echo "uv is required: https://docs.astral.sh/uv/" >&2; exit 1; }
}

# Create/refresh the virtual environment from pyproject.toml + uv.lock.
ensure_env() {
  require_uv
  local extras=()
  # if-blocks (not `[[ ]] && ...`) so a false test never trips `set -e`.
  if [[ "$(env_value DC_ENABLE_CONVERSION false)" == "true" ]]; then extras+=(--extra conversion); fi
  if [[ "$(env_value DC_ENABLE_VECTORS false)" == "true" ]]; then extras+=(--extra vectors); fi
  (cd "${ROOT_DIR}" && uv sync --quiet ${extras[@]+"${extras[@]}"})
  if [[ ! -f "${ROOT_DIR}/.env" ]]; then
    cp "${ROOT_DIR}/.env.example" "${ROOT_DIR}/.env"
    echo "Created .env from .env.example"
  fi
}

is_running() {
  [[ -f "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null
}
