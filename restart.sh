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

# --- 任意で git pull --------------------------------------------------------
if [[ "$DO_PULL" -eq 1 ]]; then
  echo "==> git pull"
  git -C "$PROJECT_DIR" pull --ff-only
fi

# --- ユニット登録確認 -------------------------------------------------------
if ! systemctl list-unit-files "${SERVICE}.service" >/dev/null 2>&1; then
  echo "${SERVICE}.service が未登録です。" >&2
  echo "先に 'bash run.sh' を一度実行して systemd unit を登録してください。" >&2
  exit 1
fi

# --- 再起動 -----------------------------------------------------------------
echo "==> sudo systemctl restart ${SERVICE}"
sudo systemctl restart "${SERVICE}"
sleep 0.5

if sudo systemctl is-active --quiet "${SERVICE}"; then
  echo "  active. ($(sudo systemctl show -p ActiveEnterTimestamp --value "${SERVICE}"))"
else
  echo "  起動失敗。直近ログ:"
  sudo journalctl -u "${SERVICE}" -n 30 --no-pager
  exit 1
fi

# --- 後処理 -----------------------------------------------------------------
case "$POST_ACTION" in
  status) sudo systemctl status "${SERVICE}" --no-pager ;;
  logs)   sudo journalctl -u "${SERVICE}" -f ;;
esac
