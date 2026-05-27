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

# --- ログヘルパ (restart.sh / run.sh と同形式) -------------------------------
T0="${EPOCHREALTIME:-$(date +%s.%N)}"
_last_ts="$T0"
log() {
  local now ts elapsed
  now="${EPOCHREALTIME:-$(date +%s.%N)}"
  ts=$(date +%H:%M:%S)
  elapsed=$(awk -v a="$now" -v b="$_last_ts" 'BEGIN { printf "%+.2fs", a - b }')
  printf '[%s %7s] %s\n' "$ts" "$elapsed" "$*"
  _last_ts="$now"
}
step() {
  printf '\n'
  log "==> $*"
}
total_elapsed() {
  awk -v a="${EPOCHREALTIME:-$(date +%s.%N)}" -v b="$T0" 'BEGIN { printf "%.1fs", a - b }'
}

log "setup_all.sh start  project=$PROJECT_DIR"

# --- [1/5] apt -------------------------------------------------------------
step "[1/5] apt packages (sudo)"
log "host/scripts/setup_apt.sh を起動"
sudo bash host/scripts/setup_apt.sh
log "[1/5] 完了"

# --- [2/5] Python ----------------------------------------------------------
step "[2/5] Python (pyenv + venv)"
log "host/scripts/setup_python.sh を起動 (初回は pyenv ビルドで数分かかります)"
bash host/scripts/setup_python.sh
log "[2/5] 完了"
if [[ -x "$PROJECT_DIR/host/.venv/bin/uvicorn" ]]; then
  log "uvicorn 確認: $($PROJECT_DIR/host/.venv/bin/uvicorn --version 2>&1 | head -1)"
fi

# --- [3/5] PaSoRi ----------------------------------------------------------
step "[3/5] PaSoRi (sudo)"
log "host/scripts/setup_nfc.sh を起動"
sudo bash host/scripts/setup_nfc.sh
log "[3/5] 完了"

# --- [4/5] systemd ---------------------------------------------------------
step "[4/5] systemd service (sudo)"
log "host/scripts/install_service.sh を起動"
sudo bash host/scripts/install_service.sh
log "[4/5] 完了"

# --- [5/5] Pico ------------------------------------------------------------
step "[5/5] Pico firmware (mpremote + flash)"
# The host service holds /dev/ttyACM0 open via serial_reader, which blocks
# mpremote from entering raw REPL. Stop the service around the flash step.
SERVICE_WAS_ACTIVE=0
if systemctl is-active --quiet pachislot-data-counter; then
  SERVICE_WAS_ACTIVE=1
  log "pachislot-data-counter を一旦停止 (/dev/ttyACM0 を解放)"
  sudo systemctl stop pachislot-data-counter
fi

log "pico/scripts/setup.sh (mpremote インストール)"
if bash pico/scripts/setup.sh && bash pico/scripts/flash.sh; then
  log "Pico フラッシュ完了"
else
  log "Pico setup/flash スキップ (Pico 未接続?)"
  log "  後で:  bash pico/scripts/setup.sh && bash pico/scripts/flash.sh"
fi

if [[ "$SERVICE_WAS_ACTIVE" -eq 1 ]]; then
  log "pachislot-data-counter を再開"
  sudo systemctl start pachislot-data-counter
fi

step "All done  total=$(total_elapsed)"
cat <<'EOF'

The pachislot-data-counter service is enabled and starts run.sh at boot.

  bash restart.sh                              # 再起動 (推奨)
  bash restart.sh --logs                       # 再起動 + ライブログ
  systemctl status pachislot-data-counter      # サービス状態
  journalctl -u pachislot-data-counter -f      # ログ追跡
  bash run.sh                                  # 手動 foreground 起動 (開発時)
  bash run.sh -d                               # 手動 detach 起動 (SSH 切断耐性)

If the Pico was not connected during setup, flash it later:
  bash pico/scripts/setup.sh
  bash pico/scripts/flash.sh
EOF
