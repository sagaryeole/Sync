#!/usr/bin/env bash
# Start the frontend dev server.
#   ./run.sh             → http://localhost:3355
#   PORT=4000 ./run.sh   → http://localhost:4000
#   INSTALL=1 ./run.sh   → npm install first
set -euo pipefail
cd "$(dirname "$0")"

if [[ "${INSTALL:-0}" == "1" || ! -d node_modules ]]; then
  npm install
fi

exec npm run dev -- --port "${PORT:-3355}"
