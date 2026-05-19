#!/usr/bin/env bash
# Start the FastAPI host server using host/.venv.
# Stdout/stderr are mirrored to $LOG_FILE (default: ./run.log) via tee.
# Any extra args are forwarded to uvicorn.
#
# Usage:
#   bash run.sh                          # 0.0.0.0:8000, log -> run.log
#   HOST=127.0.0.1 PORT=8080 bash run.sh
#   LOG_FILE=/var/log/pdc.log bash run.sh
#   bash run.sh --reload                 # dev auto-reload

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOST_DIR="$PROJECT_DIR/host"
VENV="$HOST_DIR/.venv"
LOG_FILE="${LOG_FILE:-$PROJECT_DIR/run.log}"

if [[ ! -x "$VENV/bin/uvicorn" ]]; then
  echo "uvicorn not found in $VENV. Run setup_all.sh first." >&2
  exit 1
fi

BIND_HOST="${HOST:-0.0.0.0}"
BIND_PORT="${PORT:-8000}"

cd "$HOST_DIR"

# Banner the launch so each run is distinguishable in the appended log.
{
  echo
  echo "==== run.sh started $(date -Is) host=$BIND_HOST port=$BIND_PORT args=$* ===="
} | tee -a "$LOG_FILE"

"$VENV/bin/uvicorn" app.main:app --host "$BIND_HOST" --port "$BIND_PORT" "$@" 2>&1 \
  | tee -a "$LOG_FILE"
