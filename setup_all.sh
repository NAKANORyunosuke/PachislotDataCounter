#!/usr/bin/env bash
# One-shot setup for the host (Raspberry Pi 5) side.
# Runs in order:
#   1. apt deps                 (sudo)
#   2. pyenv + Python + venv    (user)
#   3. PaSoRi udev / blacklist  (sudo)
#
# systemd autostart is intentionally NOT run here — invoke
# host/scripts/install_service.sh separately when you want the service enabled.
# Pico-side setup is also separate; see pico/scripts/setup.sh.
#
# Run from the project root:
#   bash setup_all.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR"

if [[ $EUID -eq 0 ]]; then
  echo "Run this script as a regular user. sudo will be invoked for the apt/udev steps." >&2
  exit 1
fi

echo "=== [1/3] apt packages (sudo) ==="
sudo bash host/scripts/setup_apt.sh

echo
echo "=== [2/3] Python (pyenv + venv) ==="
bash host/scripts/setup_python.sh

echo
echo "=== [3/3] PaSoRi (sudo) ==="
sudo bash host/scripts/setup_nfc.sh

cat <<'EOF'

All host setup steps completed.

To run the server:
  bash run.sh                    # 0.0.0.0:8000
  bash run.sh --reload           # dev auto-reload
  HOST=127.0.0.1 PORT=8080 bash run.sh

To install as a systemd service:
  sudo bash host/scripts/install_service.sh

For the Pico side (run on whichever machine has the Pico plugged in):
  bash pico/scripts/setup.sh
  bash pico/scripts/flash.sh
EOF
