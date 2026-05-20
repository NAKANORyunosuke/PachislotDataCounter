#!/usr/bin/env bash
# 開発用モックサーバを起動して Web UI を手動テストするためのラッパー.
# 実機(Pico)も FastAPI バックエンドも不要. 起動後に表示される URL をブラウザで開く.
#
# 使い方:
#   bash test.sh              # ポート 8000
#   PORT=9000 bash test.sh    # ポート変更
#
# sudo は不要.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
MOCK="$PROJECT_DIR/host/scripts/mock_server.py"

if [[ ! -f "$MOCK" ]]; then
  echo "mock server not found: $MOCK" >&2
  exit 1
fi

# モックサーバは標準ライブラリのみで動くので .venv は必須ではない.
# あれば .venv の Python(3.13)、無ければシステムの python3 を使う.
VENV_PY="$PROJECT_DIR/host/.venv/bin/python"
if [[ -x "$VENV_PY" ]]; then
  PYTHON="$VENV_PY"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
else
  echo "python3 not found" >&2
  exit 1
fi

# PORT 環境変数はそのまま mock_server.py に引き継がれる.
exec "$PYTHON" "$MOCK"
