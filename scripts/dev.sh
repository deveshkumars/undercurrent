#!/usr/bin/env bash
# Run the backend and the Vite dev server together (and the claude CLI shim with --with-shim).
set -euo pipefail
cd "$(dirname "$0")/.."

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

if [[ "${1:-}" == "--with-shim" ]]; then
  .venv/bin/uvicorn shim.claude_cli_api:app --port 8788 &
  pids+=($!)
fi
.venv/bin/uvicorn backend.app.main:app --reload --reload-dir backend/app --port 8010 &
pids+=($!)
(cd frontend && npm run dev) &
pids+=($!)

echo "Undercurrent: http://localhost:5173  (API http://localhost:8010/api/docs)"
wait
