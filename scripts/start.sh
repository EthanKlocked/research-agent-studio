#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ "${1:-}" == "--test" ]]; then
  export RESEARCH_TEST_MODE=1
elif [[ -n "${1:-}" ]]; then
  printf "Usage: bash scripts/start.sh [--test]\n"; exit 2
fi
[[ -f frontend/dist/index.html ]] || { printf "Run bash scripts/setup.sh first.\n"; exit 1; }
printf "Research Agent Studio: http://127.0.0.1:8765 — Ctrl+C to stop\n"
exec uv run --locked --extra dev python -m uvicorn backend.api:app --host 127.0.0.1 --port 8765
