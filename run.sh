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

# Load host/.env (PUBLIC_BASE_URL etc.) so it applies to dev runs too.
if [[ -f "$HOST_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$HOST_DIR/.env"
  set +a
fi

BIND_HOST="${HOST:-0.0.0.0}"
BIND_PORT="${PORT:-8000}"

# 既存インスタンスを止めてからポートを掴む.
if systemctl is-active --quiet pachislot-data-counter.service 2>/dev/null; then
  echo "Stopping pachislot-data-counter.service before manual run..." | tee -a "$LOG_FILE"
  sudo systemctl stop pachislot-data-counter.service || true
fi

if command -v fuser >/dev/null 2>&1; then
  if fuser -s -n tcp "$BIND_PORT" 2>/dev/null; then
    echo "Killing leftover process on tcp/$BIND_PORT..." | tee -a "$LOG_FILE"
    sudo fuser -k -n tcp "$BIND_PORT" 2>/dev/null || fuser -k -n tcp "$BIND_PORT" 2>/dev/null || true
    # ポート解放を待つ.
    for _ in 1 2 3 4 5; do
      fuser -s -n tcp "$BIND_PORT" 2>/dev/null || break
      sleep 0.5
    done
  fi
fi

cd "$HOST_DIR"

# Banner the launch so each run is distinguishable in the appended log.
{
  echo
  echo "==== run.sh started $(date -Is) host=$BIND_HOST port=$BIND_PORT args=$* ===="
} | tee -a "$LOG_FILE"

"$VENV/bin/uvicorn" app.main:app --host "$BIND_HOST" --port "$BIND_PORT" "$@" 2>&1 \
  | tee -a "$LOG_FILE"
