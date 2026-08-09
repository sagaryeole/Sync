#!/usr/bin/env bash
# Start backend + frontend together. Ctrl-C stops both.
set -euo pipefail
cd "$(dirname "$0")"

trap 'echo; echo "shutting down..."; kill 0' INT TERM EXIT

./backend/run.sh &
./frontend/run.sh &

echo "backend  → http://127.0.0.1:${BACKEND_PORT:-8000}  (docs at /docs)"
echo "frontend → http://localhost:${FRONTEND_PORT:-3355}"
echo "Ctrl-C to stop both."

wait
