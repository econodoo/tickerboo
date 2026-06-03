#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# run.sh  —  TickerBoo LOCAL DEV launcher
#
# Usage:
#   bash backend/run.sh          # from repo root
#   cd backend && bash run.sh    # from backend dir
#
# Features:
#   • --reload  (file watcher, auto-restarts on code change)
#   • DEBUG log level
#   • DB and logs in ./data and ./logs (relative to repo root)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# Resolve repo root regardless of where we're called from
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$REPO_ROOT/backend"

cd "$REPO_ROOT"

# ── Virtual environment ───────────────────────────────────────────────────────
VENV="$BACKEND_DIR/venv"
if [[ ! -d "$VENV" ]]; then
  echo "[run.sh] Creating venv at $VENV ..."
  python3 -m venv "$VENV"
  echo "[run.sh] Installing requirements ..."
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r "$BACKEND_DIR/requirements.txt"
fi

source "$VENV/bin/activate"

# ── Ensure data/logs dirs exist ───────────────────────────────────────────────
mkdir -p "$REPO_ROOT/data" "$REPO_ROOT/logs"

# ── Environment ───────────────────────────────────────────────────────────────
export TICKERBOO_ENV=dev
export TICKERBOO_HOST=0.0.0.0
export TICKERBOO_PORT="${TICKERBOO_PORT:-8688}"
export TICKERBOO_ROOT_PATH=""
export TICKERBOO_LOG_LEVEL=DEBUG
export TICKERBOO_DB_PATH="$REPO_ROOT/data/tickerboo.db"
export TICKERBOO_LOG_PATH="$REPO_ROOT/logs/tickerboo.log"

echo "────────────────────────────────────────────"
echo "  TickerBoo DEV  →  http://localhost:$TICKERBOO_PORT"
echo "  Docs           →  http://localhost:$TICKERBOO_PORT/docs"
echo "  Logs           →  $REPO_ROOT/logs/tickerboo.log"
echo "────────────────────────────────────────────"

# ── Launch ────────────────────────────────────────────────────────────────────
cd "$BACKEND_DIR"
exec uvicorn tickerboo.main:app \
  --reload \
  --host "$TICKERBOO_HOST" \
  --port "$TICKERBOO_PORT" \
  --log-level warning          # uvicorn access log; app logging handles the rest
