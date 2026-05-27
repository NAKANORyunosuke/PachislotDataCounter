#!/usr/bin/env bash
# Restart pachislot-data-counter.service.
# `git pull` でコードを更新した後にこれを叩けば反映される.
#
# Usage:
#   bash restart.sh            # 再起動だけ
#   bash restart.sh --status   # 再起動後に systemctl status を表示
#   bash restart.sh --logs     # 再起動後に journalctl -f でログ追跡 (Ctrl+C で抜ける)
#   bash restart.sh --pull     # git pull してから再起動

set -euo pipefail

SERVICE=pachislot-data-counter
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
T0=$EPOCHREALTIME   # 全体経過秒の基準 (bash 5+ で利用可)

# --- ログヘルパ --------------------------------------------------------------
# [HH:MM:SS +0.42s] message  という形で、時刻と前ステップからの経過を表示する.
_last_ts="$T0"
log() {
  local now ts elapsed
  now=$EPOCHREALTIME
  ts=$(date +%H:%M:%S)
  # bash の小数演算は printf で.
  elapsed=$(awk -v a="$now" -v b="$_last_ts" 'BEGIN { printf "%+.2fs", a - b }')
  printf '[%s %7s] %s\n' "$ts" "$elapsed" "$*"
  _last_ts="$now"
}

step() {
  printf '\n'
  log "==> $*"
}

# --- オプション処理 -----------------------------------------------------------
DO_PULL=0
POST_ACTION=""
for arg in "$@"; do
  case "$arg" in
    --pull|-p)   DO_PULL=1 ;;
    --status|-s) POST_ACTION="status" ;;
    --logs|-l)   POST_ACTION="logs" ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

log "restart.sh start  service=$SERVICE  pull=$DO_PULL  post=${POST_ACTION:-none}"

# --- 任意で git pull --------------------------------------------------------
if [[ "$DO_PULL" -eq 1 ]]; then
  step "git pull --ff-only"
  log "before:  $(git -C "$PROJECT_DIR" log -1 --oneline)"
  git -C "$PROJECT_DIR" pull --ff-only
  log "after:   $(git -C "$PROJECT_DIR" log -1 --oneline)"
fi

# --- ユニット登録確認 -------------------------------------------------------
step "systemd unit 登録確認"
if ! systemctl list-unit-files "${SERVICE}.service" >/dev/null 2>&1; then
  log "未登録: ${SERVICE}.service"
  echo "先に 'bash run.sh' を一度実行して systemd unit を登録してください。" >&2
  exit 1
fi
log "OK (登録済み)"

# --- 再起動前の状態 ----------------------------------------------------------
step "再起動前のサービス状態"
prev_state=$(systemctl is-active "${SERVICE}" 2>/dev/null || echo "inactive")
prev_pid=$(systemctl show -p MainPID --value "${SERVICE}" 2>/dev/null || echo "0")
log "is-active=$prev_state  MainPID=$prev_pid"

# --- 再起動 -----------------------------------------------------------------
step "sudo systemctl restart ${SERVICE}"
sudo systemctl restart "${SERVICE}"
log "restart コマンド完了 (systemd が起動を続けている可能性あり)"

# --- 起動完了を待つ ----------------------------------------------------------
step "起動完了を待機 (最大 10 秒)"
for i in $(seq 1 20); do
  if sudo systemctl is-active --quiet "${SERVICE}"; then
    new_pid=$(systemctl show -p MainPID --value "${SERVICE}" 2>/dev/null || echo "?")
    log "active になりました (MainPID=$new_pid, 待機 $((i * 500)) ms)"
    break
  fi
  if (( i == 20 )); then
    log "10 秒待っても active になりません。直近ログ:"
    sudo journalctl -u "${SERVICE}" -n 40 --no-pager
    exit 1
  fi
  sleep 0.5
done

# --- ヘルスチェック ----------------------------------------------------------
step "HTTP ヘルスチェック (/api/counts)"
port=$(systemctl show -p Environment --value "${SERVICE}" | tr ' ' '\n' | sed -n 's/^PORT=//p')
port="${port:-8000}"
url="http://127.0.0.1:${port}/api/counts"
if command -v curl >/dev/null 2>&1; then
  log "GET $url"
  for i in $(seq 1 10); do
    if out=$(curl -fsS --max-time 1 "$url" 2>/dev/null); then
      log "200 OK  body=$(echo "$out" | head -c 120)"
      break
    fi
    if (( i == 10 )); then
      log "5 秒以内に応答なし。journalctl で確認してください。"
    fi
    sleep 0.5
  done
else
  log "curl が無いのでスキップ"
fi

# --- 後処理 -----------------------------------------------------------------
case "$POST_ACTION" in
  status)
    step "systemctl status (no-pager)"
    sudo systemctl status "${SERVICE}" --no-pager
    ;;
  logs)
    step "journalctl -f (Ctrl+C で抜ける)"
    sudo journalctl -u "${SERVICE}" -f
    ;;
esac

step "restart.sh done"
