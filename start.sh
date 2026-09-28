#!/usr/bin/env bash
# Starts the entire LifeLine stack with one command:
#   1. LocalStack (DynamoDB + S3) via Docker Compose
#   2. The DynamoDB table + S3 bucket inside it
#   3. The backend API via `sam local start-api` (real Lambda code,
#      running in Docker, on the same network as LocalStack)
#   4. The frontend dev server (Vite), which proxies /api to the
#      backend so the browser never needs to know either backend port
#
# Run from the repo root: ./start.sh
# Stop with Ctrl+C (stops the frontend) then ./stop.sh (tears down
# LocalStack + the background SAM process).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

LOG_DIR=".run"
mkdir -p "$LOG_DIR"
SAM_LOG="$LOG_DIR/sam-local.log"
SAM_PID_FILE="$LOG_DIR/sam-local.pid"

echo "=================================================================="
echo " LifeLine — starting local stack (SAM CLI + LocalStack)"
echo "=================================================================="

# --- 0. Sanity checks -------------------------------------------------
command -v docker >/dev/null || { echo "ERROR: docker not found. Rebuild the devcontainer."; exit 1; }
command -v sam >/dev/null || { echo "ERROR: sam not found. Run: pip install --user aws-sam-cli"; exit 1; }
command -v aws >/dev/null || { echo "ERROR: aws CLI not found."; exit 1; }

# --- 1. LocalStack ------------------------------------------------------
echo "==> Starting LocalStack (docker compose)..."
docker compose up -d

echo "==> Waiting for LocalStack to be healthy..."
for i in $(seq 1 40); do
  if curl -sf http://localhost:4566/_localstack/health >/dev/null 2>&1; then
    echo "    LocalStack is up."
    break
  fi
  if [ "$i" -eq 40 ]; then
    echo "ERROR: LocalStack did not become healthy in time. Check: docker compose logs localstack"
    exit 1
  fi
  sleep 2
done

# --- 2. DynamoDB table + S3 bucket --------------------------------------
bash scripts/setup-local-resources.sh

# --- 3. Backend: sam build + sam local start-api ------------------------
echo "==> Building the backend (sam build)..."
(cd infrastructure && sam build --template template.yaml)

# Stop any previous run's leftover process before starting a fresh one.
if [ -f "$SAM_PID_FILE" ] && kill -0 "$(cat "$SAM_PID_FILE")" 2>/dev/null; then
  echo "==> Stopping a previous sam local process..."
  kill "$(cat "$SAM_PID_FILE")" 2>/dev/null || true
  sleep 1
fi

echo "==> Starting the backend API (sam local start-api) in the background..."
echo "    Logs: tail -f $SAM_LOG"
(
  cd infrastructure
  nohup sam local start-api \
    --template .aws-sam/build/template.yaml \
    --env-vars env.local.json \
    --docker-network lifeline-net \
    --add-host localstack:host-gateway \
    --warm-containers EAGER \
    --port 3000 \
    --host 0.0.0.0 \
    > "../$SAM_LOG" 2>&1 &
  echo $! > "../$SAM_PID_FILE"
)

echo "==> Waiting for the backend API to respond..."
for i in $(seq 1 60); do
  code=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://localhost:3000/auth/login \
    -H "Content-Type: application/json" -d '{}' 2>/dev/null || echo "000")
  if [ "$code" != "000" ]; then
    echo "    Backend API is up (http $code on a test request — that's expected)."
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "ERROR: backend API did not come up in time. Check: tail -f $SAM_LOG"
    echo "(First run downloads the Lambda runtime Docker image — can take a minute or two.)"
    exit 1
  fi
  sleep 2
done

# --- 4. Frontend ----------------------------------------------------------
echo "=================================================================="
echo " Backend ready. Starting the frontend (Vite) in the foreground."
echo " Open the forwarded port 5173 — Codespaces will prompt you, or use"
echo " the 'Ports' tab in VS Code."
echo ""
echo " Press Ctrl+C to stop the frontend, then run ./stop.sh to tear"
echo " down LocalStack and the background backend process."
echo "=================================================================="
cd frontend
npm run dev -- --host 0.0.0.0
