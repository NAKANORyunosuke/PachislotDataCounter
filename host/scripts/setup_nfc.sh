#!/usr/bin/env bash
# Setup script for PaSoRi RC-S300 (or any CCID-compliant reader) on
# Raspberry Pi 5. Installs the PC/SC stack and pyscard into host/.venv.
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

echo "==> Installing PC/SC stack"
apt-get update
apt-get install -y \
  libpcsclite-dev \
  libusb-1.0-0 \
  libusb-1.0-0-dev \
  pcscd \
  pcsc-tools \
  opensc \
  python3-dev

echo "==> Enabling and starting pcscd"
systemctl enable --now pcscd

# Debian Bookworm の pcscd は polkit でアクセス制御するため、SSH/systemd 経由で
# 実行する uvicorn プロセスから接続を拒否される. 対象ユーザーに明示的に許可する.
POLKIT_RULE=/etc/polkit-1/rules.d/50-pachislot-pcscd.rules
echo "==> Writing polkit rule to $POLKIT_RULE (allow user $TARGET_USER)"
cat >"$POLKIT_RULE" <<EOF
// Allow the pachislot data counter service user to access pcscd / cards.
polkit.addRule(function(action, subject) {
  if ((action.id == "org.debian.pcsc-lite.access_pcsc" ||
       action.id == "org.debian.pcsc-lite.access_card") &&
      subject.user == "$TARGET_USER") {
    return polkit.Result.YES;
  }
});
EOF

echo "==> Restarting pcscd to pick up polkit rule"
systemctl restart pcscd
systemctl status pcscd --no-pager || true

if [[ -d "$VENV" ]]; then
  echo "==> Installing Python deps into $VENV"
  sudo -u "$TARGET_USER" "$VENV/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
else
  echo "!! Virtualenv not found at $VENV. Create it first:"
  echo "     bash host/scripts/setup_python.sh"
fi

cat <<EOF

Done.

Verify the reader is visible:
  pcsc_scan
  $VENV/bin/python -c "from smartcard.System import readers; print(readers())"

Tap a FeliCa card; pcsc_scan should print its ATR and IDm.
EOF
