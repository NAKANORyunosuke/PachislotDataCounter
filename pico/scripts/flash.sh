#!/usr/bin/env bash
# Copy pico/main.py onto the connected Raspberry Pi Pico via mpremote,
# then soft-reset so the new code takes effect immediately.
#
# Usage:
#   bash pico/scripts/flash.sh             # auto-detect serial device
#   bash pico/scripts/flash.sh /dev/ttyACM0

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$PROJECT_DIR/.venv"
MPREMOTE="$VENV/bin/mpremote"
MAIN="$PROJECT_DIR/main.py"

if [[ ! -x "$MPREMOTE" ]]; then
  echo "mpremote not found. Run pico/scripts/setup.sh first." >&2
  exit 1
fi

if [[ ! -f "$MAIN" ]]; then
  echo "main.py not found at $MAIN" >&2
  exit 1
fi

PORT="${1:-}"
if [[ -n "$PORT" ]]; then
  echo "==> Flashing main.py to $PORT"
  "$MPREMOTE" connect "$PORT" fs cp "$MAIN" :main.py
  "$MPREMOTE" connect "$PORT" reset
else
  echo "==> Flashing main.py (auto-detect)"
  "$MPREMOTE" fs cp "$MAIN" :main.py
  "$MPREMOTE" reset
fi

echo
echo "Done. The Pico has been reset and is running the new main.py."
