#!/usr/bin/env bash
# Start the FastAPI host server using host/.venv.
# Stdout/stderr are mirrored to $LOG_FILE (default: ./run.log).
# Any extra args are forwarded to uvicorn.
#
# Usage:
#   bash run.sh                          # 0.0.0.0:8000, foreground, log -> run.log
#   HOST=127.0.0.1 PORT=8080 bash run.sh
#   LOG_FILE=/var/log/pdc.log bash run.sh
#   bash run.sh --reload                 # dev auto-reload (foreground)
#   bash run.sh -d                       # SSH 切断後も生存するバックグラウンド起動
#   bash run.sh --detach --reload        # detach + uvicorn auto-reload

set -euo pipefail

# --- detach (SSH 切断後も生存させる) ----------------------------------------
# 先頭の -d / --detach を吸って setsid + nohup で自分自身を再起動し、
# 親はすぐに PID を出して exit する. 残りの引数は再起動時に渡す.
if [[ "${1:-}" == "-d" || "${1:-}" == "--detach" ]]; then
  shift
  LOG_FILE_INIT="${LOG_FILE:-$(cd "$(dirname "$0")" && pwd)/run.log}"
  echo "Detaching run.sh (logs -> $LOG_FILE_INIT)"
  # </dev/null で stdin を切り離し、stdout/stderr をログへ. setsid で新セッ
  # ション化することで親シェル (sshd) が死んでも SIGHUP を受け取らない.
  setsid nohup bash "$0" "$@" </dev/null >>"$LOG_FILE_INIT" 2>&1 &
  PID=$!
  echo "Started detached (pid $PID). 切断 OK."
  echo "  tail:  tail -f $LOG_FILE_INIT"
  echo "  stop:  kill $PID    # or sudo systemctl stop pachislot-data-counter"
  exit 0
fi

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
HOST_DIR="$PROJECT_DIR/host"
VENV="$HOST_DIR/.venv"
LOG_FILE="${LOG_FILE:-$PROJECT_DIR/run.log}"

if [[ ! -x "$VENV/bin/uvicorn" ]]; then
  echo "uvicorn not found in $VENV. Run setup_all.sh first." >&2
  exit 1
fi

# --- systemd unit を冪等にインストール (未登録 or 内容が古い場合のみ) ---------
# 順序: 既存サービス停止 → ここで登録/更新 → このスクリプトの末尾で起動
ensure_service_installed() {
  local src="$HOST_DIR/systemd/pachislot-data-counter.service"
  local dst="/etc/systemd/system/pachislot-data-counter.service"
  if [[ ! -f "$src" ]]; then
    return  # ソースが無いリポジトリでは何もしない
  fi
  if [[ -f "$dst" ]] && cmp -s "$src" "$dst" 2>/dev/null; then
    return  # 既に同一内容で登録済み
  fi
  echo "==> Installing systemd unit: $dst"
  if ! sudo -n true 2>/dev/null && [[ ! -t 0 ]]; then
    # detach 中 (tty 無し) で sudo がパスワード要求してくると詰むのでスキップ.
    echo "  (sudo non-interactive 不可。detach 中はスキップ。手動で sudo bash host/scripts/install_service.sh を実行してください。)"
    return
  fi
  if ! sudo install -m 0644 "$src" "$dst"; then
    echo "  (sudo install 失敗。service 登録をスキップして起動を続行します。)"
    return
  fi
  sudo systemctl daemon-reload || true
  sudo systemctl enable pachislot-data-counter 2>/dev/null || true
  echo "  systemd unit 登録完了 (自動起動有効化)."
}

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

# サービス停止 (上で) → systemd unit を登録/更新 → このあと uvicorn 起動.
ensure_service_installed

cd "$HOST_DIR"

# Banner the launch so each run is distinguishable in the appended log.
banner="==== run.sh started $(date -Is) host=$BIND_HOST port=$BIND_PORT args=$* ===="
if [[ -t 1 ]]; then
  # Foreground: stdout が tty なのでログにも mirror.
  printf '\n%s\n' "$banner" | tee -a "$LOG_FILE"
  "$VENV/bin/uvicorn" app.main:app --host "$BIND_HOST" --port "$BIND_PORT" "$@" 2>&1 \
    | tee -a "$LOG_FILE"
else
  # Detached / リダイレクト経由: stdout が既にログに向いているので append のみ.
  printf '\n%s\n' "$banner" >>"$LOG_FILE"
  exec "$VENV/bin/uvicorn" app.main:app --host "$BIND_HOST" --port "$BIND_PORT" "$@" >>"$LOG_FILE" 2>&1
fi
