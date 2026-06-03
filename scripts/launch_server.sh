#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# launch_server.sh  —  TickerBoo PRODUCTION launcher
#
# Called by systemd unit (tickerboo.service).
# Do NOT run this directly for dev — use backend/run.sh instead.
#
# Key differences from run.sh:
#   • No --reload
#   • Binds to 127.0.0.1 only (nginx proxies in)
#   • --workers 1  (APScheduler + in-process cache must be single-process)
#   • INFO log level
#   • Root path /tb set for reverse-proxy subpath
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

cd "$REPO_ROOT"

VENV="$BACKEND_DIR/venv"
if [[ ! -f "$VENV/bin/activate" ]]; then
  echo "[launch_server.sh] ERROR: venv not found at $VENV"
  echo "  Run this once on the server:"
  echo "    python3 -m venv $VENV"
  echo "    $VENV/bin/pip install -r $BACKEND_DIR/requirements.txt"
  exit 1
fi

source "$VENV/bin/activate"

mkdir -p "$REPO_ROOT/data" "$REPO_ROOT/logs"

export TICKERBOO_ENV=prod
export TICKERBOO_HOST=127.0.0.1
export TICKERBOO_PORT="${TICKERBOO_PORT:-8688}"
export TICKERBOO_ROOT_PATH="/tb"
export TICKERBOO_LOG_LEVEL=INFO
export TICKERBOO_DB_PATH="$REPO_ROOT/data/tickerboo.db"
export TICKERBOO_LOG_PATH="$REPO_ROOT/logs/tickerboo.log"

echo "[launch_server.sh] Starting TickerBoo prod on 127.0.0.1:$TICKERBOO_PORT ..."

cd "$BACKEND_DIR"
exec uvicorn tickerboo.main:app \
  --host "$TICKERBOO_HOST" \
  --port "$TICKERBOO_PORT" \
  --workers 1 \
  --log-level warning \
  --access-log \
  --proxy-headers \
  --forwarded-allow-ips="127.0.0.1"
