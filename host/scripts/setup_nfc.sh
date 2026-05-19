#!/usr/bin/env bash
# Setup script for PaSoRi RC-S380 on Raspberry Pi 5.
# - Installs libusb dependency
# - Installs Python deps into the host/.venv project venv
# - Drops a udev rule so the reader is accessible without sudo
# - Blacklists kernel modules that would grab the device first
#
# Run from the project root:
#   sudo bash host/scripts/setup_nfc.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root: sudo bash host/scripts/setup_nfc.sh" >&2
  exit 1
fi

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$PROJECT_DIR/.venv"
TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || echo nakano)}"

echo "==> Installing system packages"
apt-get update
apt-get install -y libusb-1.0-0 libusb-1.0-0-dev python3-dev

UDEV_RULE=/etc/udev/rules.d/99-pasori.rules
echo "==> Writing udev rule to $UDEV_RULE"
cat >"$UDEV_RULE" <<'EOF'
# Sony PaSoRi RC-S380
SUBSYSTEM=="usb", ATTRS{idVendor}=="054c", ATTRS{idProduct}=="06c1", GROUP="plugdev", MODE="0664"
SUBSYSTEM=="usb", ATTRS{idVendor}=="054c", ATTRS{idProduct}=="06c3", GROUP="plugdev", MODE="0664"
EOF

echo "==> Ensuring user $TARGET_USER is in plugdev group"
usermod -aG plugdev "$TARGET_USER" || true

BLACKLIST=/etc/modprobe.d/blacklist-nfc.conf
echo "==> Blacklisting kernel NFC modules in $BLACKLIST"
cat >"$BLACKLIST" <<'EOF'
blacklist port100
blacklist nfc
EOF

echo "==> Reloading udev rules"
udevadm control --reload-rules
udevadm trigger

if [[ -d "$VENV" ]]; then
  echo "==> Installing Python deps into $VENV"
  sudo -u "$TARGET_USER" "$VENV/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
else
  echo "!! Virtualenv not found at $VENV. Create it first:"
  echo "     cd host && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
fi

echo
echo "Done. Unplug and replug the PaSoRi (or reboot) for udev/blacklist to take effect."
echo "Verify with:  $VENV/bin/python -m nfc"
