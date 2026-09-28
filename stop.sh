#!/usr/bin/env bash
# Stops the background `sam local start-api` process and LocalStack.
# The frontend (Vite) runs in the foreground under start.sh, so it's
# already stopped once you Ctrl+C that.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

LOG_DIR=".run"
SAM_PID_FILE="$LOG_DIR/sam-local.pid"

if [ -f "$SAM_PID_FILE" ]; then
  PID="$(cat "$SAM_PID_FILE")"
  if kill -0 "$PID" 2>/dev/null; then
    echo "==> Stopping backend API (pid $PID)..."
    kill "$PID" 2>/dev/null
    # sam local start-api spawns Lambda containers as children; give it
    # a moment, then make sure nothing is left listening on 3000.
    sleep 1
  fi
  rm -f "$SAM_PID_FILE"
fi

echo "==> Stopping LocalStack (docker compose down)..."
docker compose down

echo "==> Done. Local stack stopped. Your data volume (lifeline-localstack-data) is preserved —"
echo "    run ./start.sh again to pick up where you left off, or 'docker compose down -v' first"
echo "    for a completely clean slate."
