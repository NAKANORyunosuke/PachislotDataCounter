#!/usr/bin/env bash
# Install and enable the pachislot-data-counter systemd service.
# Kept separate from setup_all.sh so autostart is an explicit, deliberate step.
#
# Run from anywhere:
#   sudo bash host/scripts/install_service.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo bash host/scripts/install_service.sh" >&2
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
UNIT_SRC="$PROJECT_DIR/systemd/pachislot-data-counter.service"
UNIT_DST="/etc/systemd/system/pachislot-data-counter.service"

if [[ ! -f "$UNIT_SRC" ]]; then
  echo "Unit file not found at $UNIT_SRC" >&2
  exit 1
fi

echo "==> Installing $UNIT_DST"
cp "$UNIT_SRC" "$UNIT_DST"

echo "==> systemctl daemon-reload"
systemctl daemon-reload

echo "==> Enabling (boot autostart) and (re)starting pachislot-data-counter"
systemctl enable pachislot-data-counter
systemctl restart pachislot-data-counter

echo
systemctl status pachislot-data-counter --no-pager || true
