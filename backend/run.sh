#!/usr/bin/env bash
# Start the backend API server.
#   ./run.sh              → http://127.0.0.1:8000
#   PORT=9000 ./run.sh    → http://127.0.0.1:9000
#   HOST=0.0.0.0 ./run.sh → bind all interfaces (see warning below)
#   INSTALL=1 ./run.sh    → pip install deps first
set -euo pipefail
cd "$(dirname "$0")"

# Bind loopback by default. 0.0.0.0 exposes this API — which can place trades
# and has no authentication — to every device on your network. Opt in explicitly.
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"

if [[ "${INSTALL:-0}" == "1" ]]; then
  python3 -m pip install -r requirements.txt
fi

exec python3 -m uvicorn main:app --host "$HOST" --port "$PORT" --reload
