#!/usr/bin/env bash
# Local two-process development: keep Python PSE API and React/Node frontend alive.
set -euo pipefail
repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_dir"
if [[ ! -x .venv/bin/python ]]; then
  echo "Missing .venv/bin/python. Run: python3.11 -m venv .venv && .venv/bin/python -m pip install -e '.[dev,api]'" >&2
  exit 2
fi
if [[ ! -d node_modules && ! -d apps/gemini-fantasy-console/node_modules ]]; then
  echo "Missing Node dependencies. Run: npm ci --include=optional from the repository root." >&2
  exit 2
fi
if ! curl -fsS --max-time 1 http://127.0.0.1:8000/health >/dev/null 2>&1; then
  echo "Starting Python PSE API at http://127.0.0.1:8000"
  .venv/bin/python -m uvicorn player_state_engine.api.operational:app --host 127.0.0.1 --port 8000 &
  api_pid=$!
else
  echo "Using existing Python API at http://127.0.0.1:8000"
  api_pid=""
fi
cleanup() {
  if [[ -n "$api_pid" ]]; then
    kill "$api_pid" 2>/dev/null || true
    wait "$api_pid" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM
export PSE_API_BASE_URL="http://127.0.0.1:8000"
echo "Starting Fourth Down Lab at http://127.0.0.1:3000"
npm run frontend:dev
