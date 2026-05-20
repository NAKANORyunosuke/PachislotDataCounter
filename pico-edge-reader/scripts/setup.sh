#!/usr/bin/env bash
# Set up pico-edge-reader/.venv with mpremote -- the official MicroPython tool
# used to push files (e.g. main.py) onto a Raspberry Pi Pico over USB serial.
#
# This runs on the *dev machine* (or the RPi5) that will program the Pico,
# not on the Pico itself. The Pico must already have MicroPython flashed.
#
# Run from anywhere:
#   bash pico-edge-reader/scripts/setup.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$PROJECT_DIR/.venv"

if [[ ! -d "$VENV" ]]; then
  echo "==> Creating venv at $VENV"
  python3 -m venv "$VENV"
else
  echo "==> Venv already exists at $VENV"
fi

echo "==> Upgrading pip"
"$VENV/bin/pip" install --upgrade pip

echo "==> Installing mpremote"
"$VENV/bin/pip" install mpremote

cat <<EOF

Done.
  mpremote : $("$VENV/bin/mpremote" --help | head -n 1 || true)

Next:
  bash pico-edge-reader/scripts/flash.sh              # auto-detect Pico
  bash pico-edge-reader/scripts/flash.sh /dev/ttyACM0
EOF
