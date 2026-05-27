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

# --- ログヘルパ -------------------------------------------------------------
# 各ステップを [HH:MM:SS +X.XXs] 形式で出力. tee 経由なのでログにも残る.
_last_ts="${EPOCHREALTIME:-$(date +%s.%N)}"
log() {
  local now ts elapsed
  now="${EPOCHREALTIME:-$(date +%s.%N)}"
  ts=$(date +%H:%M:%S)
  elapsed=$(awk -v a="$now" -v b="$_last_ts" 'BEGIN { printf "%+.2fs", a - b }')
  if [[ -t 1 ]]; then
    printf '[%s %7s] %s\n' "$ts" "$elapsed" "$*" | tee -a "$LOG_FILE"
  else
    printf '[%s %7s] %s\n' "$ts" "$elapsed" "$*" >>"$LOG_FILE"
  fi
  _last_ts="$now"
}
step() {
  printf '\n' >&2 2>/dev/null || true
  log "==> $*"
}

if [[ ! -x "$VENV/bin/uvicorn" ]]; then
  echo "uvicorn not found in $VENV. Run setup_all.sh first." >&2
  exit 1
fi

step "run.sh start  args=$*  log=$LOG_FILE"

# systemd 配下で動いているかを INVOCATION_ID で検出.
# ExecStart=bash run.sh で起動された場合、自分自身が active なサービスなので
# 「既存サービス停止 → unit 登録」を実行すると自殺ループになる. systemd 経由
# なら前処理を全部スキップして uvicorn の起動だけ行う.
UNDER_SYSTEMD=0
if [[ -n "${INVOCATION_ID:-}" ]]; then
  UNDER_SYSTEMD=1
  log "systemd 配下 (INVOCATION_ID=$INVOCATION_ID) — 前処理スキップ"
fi

# --- systemd unit を冪等にインストール (未登録 or 内容が古い場合のみ) ---------
ensure_service_installed() {
  local src="$HOST_DIR/systemd/pachislot-data-counter.service"
  local dst="/etc/systemd/system/pachislot-data-counter.service"
  if [[ ! -f "$src" ]]; then
    log "ソース unit が無いのでスキップ ($src)"
    return
  fi
  if [[ -f "$dst" ]] && cmp -s "$src" "$dst" 2>/dev/null; then
    log "既に同一内容で登録済み ($dst)"
    return
  fi
  log "登録/更新が必要: $dst"
  if ! sudo -n true 2>/dev/null && [[ ! -t 0 ]]; then
    log "  非対話 sudo が通らない (detach 中)。スキップ。"
    log "  手動で sudo bash host/scripts/install_service.sh を実行してください。"
    return
  fi
  if ! sudo install -m 0644 "$src" "$dst"; then
    log "  sudo install 失敗。スキップして起動を続行。"
    return
  fi
  log "  unit 配置 OK"
  sudo systemctl daemon-reload || true
  log "  daemon-reload 完了"
  sudo systemctl enable pachislot-data-counter 2>/dev/null || true
  log "  enable 完了 (自動起動有効化)"
}

# Load host/.env (PUBLIC_BASE_URL etc.) so it applies to dev runs too.
step ".env 読み込み"
if [[ -f "$HOST_DIR/.env" ]]; then
  set -a
  # shellcheck source=/dev/null
  source "$HOST_DIR/.env"
  set +a
  log "$HOST_DIR/.env を反映"
else
  log "$HOST_DIR/.env なし (スキップ)"
fi

BIND_HOST="${HOST:-0.0.0.0}"
BIND_PORT="${PORT:-8000}"

if [[ "$UNDER_SYSTEMD" -eq 0 ]]; then
  # --- 既存サービス停止 -----------------------------------------------------
  step "既存サービス停止 (pachislot-data-counter)"
  if systemctl is-active --quiet pachislot-data-counter.service 2>/dev/null; then
    log "active を検出。stop を発行"
    sudo systemctl stop pachislot-data-counter.service || true
    log "stop 完了"
  else
    log "inactive (停止不要)"
  fi

  # --- ポート解放 ----------------------------------------------------------
  step "ポート tcp/$BIND_PORT の解放確認"
  if command -v fuser >/dev/null 2>&1; then
    if fuser -s -n tcp "$BIND_PORT" 2>/dev/null; then
      log "占有プロセスを検出 → kill"
      sudo fuser -k -n tcp "$BIND_PORT" 2>/dev/null || fuser -k -n tcp "$BIND_PORT" 2>/dev/null || true
      for i in 1 2 3 4 5; do
        if ! fuser -s -n tcp "$BIND_PORT" 2>/dev/null; then
          log "解放確認 ($((i*500)) ms 経過)"
          break
        fi
        log "  待機中... ($((i*500)) ms)"
        sleep 0.5
      done
    else
      log "占有なし"
    fi
  else
    log "fuser コマンドが無いのでスキップ"
  fi

  # --- unit 登録 (停止後に行う) -------------------------------------------
  step "systemd unit 登録/更新"
  ensure_service_installed
fi

cd "$HOST_DIR"

# --- uvicorn 起動 -----------------------------------------------------------
step "uvicorn 起動  host=$BIND_HOST port=$BIND_PORT extra=$*"
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
