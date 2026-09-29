#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
command -v uv >/dev/null || { printf "Install uv before setup.\n"; exit 1; }
command -v npm >/dev/null || { printf "Install Node.js 22 before setup.\n"; exit 1; }
uv sync --locked --extra dev
npm --prefix frontend ci
npm --prefix frontend run build
