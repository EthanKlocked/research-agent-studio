#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --locked --extra dev python -m pytest tests -q
npm --prefix frontend test -- --run
npm --prefix frontend run build
