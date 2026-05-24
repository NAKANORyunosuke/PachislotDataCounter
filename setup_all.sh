#!/usr/bin/env bash
# One-shot setup for the host (Raspberry Pi 5) side.
# Runs in order:
#   1. apt deps                 (sudo)
#   2. pyenv + Python + venv    (user)
#   3. PaSoRi udev / blacklist  (sudo)
#   4. systemd service          (sudo)  -- boot autostart of run.sh
#   5. Pico mpremote + flash            -- skipped if no Pico is connected
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

echo "=== [1/5] apt packages (sudo) ==="
sudo bash host/scripts/setup_apt.sh

echo
echo "=== [2/5] Python (pyenv + venv) ==="
bash host/scripts/setup_python.sh

echo
echo "=== [3/5] PaSoRi (sudo) ==="
sudo bash host/scripts/setup_nfc.sh

echo
echo "=== [4/5] systemd service (sudo) ==="
sudo bash host/scripts/install_service.sh

echo
echo "=== [5/5] Pico firmware (mpremote + flash) ==="
# The host service holds /dev/ttyACM0 open via serial_reader, which blocks
# mpremote from entering raw REPL. Stop the service around the flash step.
SERVICE_WAS_ACTIVE=0
if systemctl is-active --quiet pachislot-data-counter; then
  SERVICE_WAS_ACTIVE=1
  echo "==> Stopping pachislot-data-counter to release /dev/ttyACM0"
  sudo systemctl stop pachislot-data-counter
fi

# Flash the Pico if it is plugged in; skip otherwise. A failing command
# inside an 'if' condition is exempt from 'set -e', so setup is not aborted.
if bash pico/scripts/setup.sh && bash pico/scripts/flash.sh; then
  echo "Pico flashed."
else
  echo "Pico setup/flash skipped (Pico not connected?)."
  echo "Plug in the Pico and run pico/scripts/setup.sh + flash.sh manually."
fi

if [[ "$SERVICE_WAS_ACTIVE" -eq 1 ]]; then
  echo "==> Restarting pachislot-data-counter"
  sudo systemctl start pachislot-data-counter
fi

cat <<'EOF'

All setup steps completed. The pachislot-data-counter service is enabled
and starts run.sh at boot.

  systemctl status pachislot-data-counter      # check the service
  journalctl -u pachislot-data-counter -f      # follow logs
  bash run.sh                                  # or run manually (dev)

If the Pico was not connected during setup, flash it later:
  bash pico/scripts/setup.sh
  bash pico/scripts/flash.sh
EOF
