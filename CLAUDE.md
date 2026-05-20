# CLAUDE.md

このリポジトリで作業する際の Claude 向けガイド.

## プロジェクト概要

家スロ用データカウンター. Raspberry Pi Pico がパチスロ実機のドライ接点出力(IN/OUT/RB/BB)を GPIO で読み取り USB シリアルで Raspberry Pi 5 に送信、RPi5 上の FastAPI が SQLite に記録し Web UI と SSE で配信する.

PaSoRi RC-S300 (USB 054c:0dc9, PaSoRi 4.0) を RPi5 に接続し、IC カードでユーザー識別とセッション管理ができる. RC-S300 は nfcpy 非対応のため、PC/SC (`pcscd`) + `pyscard` 経由で扱う. RC-S380 (旧型, USB 054c:06c1/06c3) はこのスタックでは扱わない.

## ディレクトリ構造(重要)

`host/`(RPi5)と Pico ファームウェア(`pico/` / `pico-edge-reader/`)は **完全に独立した別ターゲット** のコードです. 混在させないこと.

```
PachislotDataCounter/
├── host/         # Raspberry Pi 5 (CPython 3.13.5, FastAPI/SQLite)
│   ├── app/      #   バックエンド
│   ├── static/   #   Web UI
│   ├── data/     #   SQLite (events.db)
│   ├── systemd/  #   サービスユニット
│   ├── scripts/  #   セットアップスクリプト
│   ├── pyproject.toml
│   ├── .python-version  # 3.13.5
│   └── requirements.txt
├── pico/         # Raspberry Pi Pico (MicroPython) — 本番ファームウェア
│   └── main.py
└── pico-edge-reader/  # Pico 汎用ファームウェア(立ち下がり検出の再利用版)
    └── main.py
```

- ラズパイ5に置くのは `host/` 配下のみ.
- `pico/main.py` と `pico-edge-reader/main.py` は **MicroPython** で動く. CPython の構文や標準ライブラリを前提にしないこと(`asyncio`, `pathlib`, `typing` などは使えない).
- 本番デプロイ対象は `pico/`(IN/OUT/RB/BB をイベント名で出力). `pico-edge-reader/` は信号の意味を持たない汎用版で、`PINS` の書き換えで他用途に流用するための再利用コード.
- 何かを編集するとき、対象がどのターゲットかを最初に意識する.

## 必要環境

- **Python 3.13.5**(`host/.python-version` で固定. `pyproject.toml` の `requires-python` は `>=3.13`)
- Raspberry Pi OS Bookworm 標準の 3.11 では動かない. pyenv で 3.13.5 を入れる前提.

## よく使うコマンド

すべて `host/` 配下から実行:

```bash
cd host
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000   # 開発起動
.venv/bin/python -c "from app.db import init_db; init_db()"  # DB マイグレーション
.venv/bin/python -c "from smartcard.System import readers; print(readers())"  # PaSoRi 認識確認
pcsc_scan                                                    # PaSoRi の生疎通確認(pcsc-tools)
sudo bash scripts/setup_nfc.sh                                # PaSoRi 初期設定(pcscd + pyscard. プロジェクトルートから sudo bash host/scripts/setup_nfc.sh でも可)
```

## アーキテクチャ要点

### 並行タスク
`host/app/main.py` の lifespan で 2 つの asyncio タスクが走る:
- `run_reader` (`serial_reader.py`): Pico からの USB シリアルを read、イベントを DB と SSE に流す
- `run_nfc_reader` (`nfc_reader.py`): pyscard で PC/SC リーダーを別スレッド (run_in_executor) でポーリング(300ms 間隔, APDU `FF CA 00 00 00` で IDm 取得)、タップを `session_manager.handle_tap` に流す. リーダーは pcscd が掴むので udev ルールや libusb 直叩きは不要

### pcscd の polkit アクセス制御(非自明・ハマりどころ)
Debian Bookworm の `pcscd` は polkit でアクセス制御する. SSH セッションや systemd 配下で動く uvicorn プロセスはセッション扱いされず、`pcscd` ログに `Rejected` が出てカードを読めない(`pcsc_scan` を対話シェルで叩くと動くのに、というズレが起きる). `setup_nfc.sh` が `/etc/polkit-1/rules.d/50-pachislot-pcscd.rules` を配置し、対象ユーザーに `org.debian.pcsc-lite.access_pcsc` / `access_card` を許可することで解消している. ユーザー名は `setup_nfc.sh` 実行時の `SUDO_USER` で焼き込まれるので、サービス実行ユーザーを変えたら再実行が必要.

### セッション状態遷移(非自明)
`session_manager.SessionManager` がアクティブセッションを単一スロットで保持:
- アクティブなし + タップ → 新規開始
- アクティブあり + 同じカード → 終了 (`end_reason=same_card_retap`)
- アクティブあり + 別カード → 旧終了 (`end_reason=other_card`) + 新規開始

`serial_reader.py` はイベントを DB に挿入する直前に `session_manager.active_session_id` を参照し、`events.session_id` に紐付ける. カード未タップ時のイベントは `session_id = NULL` で記録される.

### 未登録カードの登録フロー
- 未登録 IDm 検知 → `users` に `registered=0` で仮レコード作成、`registration_token` 発行
- SSE で `register_required` を配信 → フロントが `/api/qr?token=...` の QR を表示
- ユーザーがスマホで `/register?token=...` を開いて名前を POST すると `users` 更新 + `user_registered` SSE 配信

### QR の URL
`PUBLIC_BASE_URL` 環境変数(Cloudflare Tunnel 等の公開ホスト名)があればそれを使う. 未設定時はリクエスト元のホスト名で組み立てる. 設定値は `host/.env` に書く(`host/.env.example` がテンプレート). systemd は `EnvironmentFile` で、`run.sh` は起動時に source で読む.

### パネル表示プロファイル(非自明)
ユーザーごとに「モニタに表示するパネル」を選べる. `users.display_settings`(JSON, 例 `{"hidden_panels": [...]}`)に保存. レイアウトは 2 層:
- アイドル時 … モニタ側 `localStorage` のデフォルトレイアウト
- セッション中 … カードのユーザーの `display_settings` を反映(無ければデフォルト)

設定は `/settings?user=...`(セッション中パネルの QR から開く)で編集 → `/api/users/{id}/settings` に POST → `settings_updated` SSE で全モニタへ即時反映.

### SSE イベント形式
クライアントは EventSource で `/api/events/stream` を購読. 内部メッセージは `kind` フィールドで判別:
- `event` … パチスロイベント(IN/OUT/BB/RB)
- `session_start` / `session_end`
- `register_required` / `user_registered`
- `settings_updated` … ユーザーのパネル表示プロファイル更新

初回接続時のみ別 SSE event 名 `snapshot` で累計カウントを送る.

### DB スキーマ
`host/data/events.db` (SQLite). `host/app/db.py` の `SCHEMA` 定数に DDL がまとまっている. レガシー DB(`session_id` 列がない `events`、`display_settings` 列がない `users`)は `init_db()` 時に自動 ALTER で吸収.

```
events    (id, ts, type, session_id)
users     (id, card_idm UNIQUE, name, registered, registration_token, created_at, display_settings)
sessions  (id, user_id, started_at, ended_at, end_reason)
```

## コーディング規約

- Python 標準ライブラリと PEP 604 (`str | None`) / PEP 585 (`dict[str, int]`) を使う(3.13 前提).
- 過剰な抽象化や将来要件のためのレイヤーを足さない. シンプルさ優先.
- コメントは「なぜ」を残す目的のみ. 何をしているかは識別子で表現する.
- 既存のスタイルに揃える(`host/app/` の各モジュールがリファレンス).
- フロントは生 JS + Chart.js(CDN). フレームワーク導入はしない方針.

## やってはいけないこと

- `pico/main.py` / `pico-edge-reader/main.py` に CPython 専用構文を持ち込む(MicroPython 互換が壊れる).
- `host/.venv/` をリポジトリにコミットする(`.gitignore` 済み).
- `host/data/events.db` をコミットする(`.gitignore` 済み).
- 既存 DB に対する破壊的マイグレーション. 必要なら `db.py` の `LEGACY_MIGRATIONS` に追加して `init_db` で安全に適用.
- 認証や個人情報を扱う前提の機能拡張(個人利用想定なのでスコープ外).

## テスト

現状ユニットテストはない. 動作確認は:

1. `host/.venv/bin/python -c "from app.main import app; print([r.path for r in app.routes])"` でルート登録を確認
2. `bash run.sh` で起動し `curl http://localhost:8000/api/counts`
3. `bash test.sh` でモックサーバを起動すると、実機もバックエンドも無しで Web UI(演出・スランプ・表示プロファイル切替)を目視確認できる
4. PaSoRi / pcscd がない環境では `nfc_reader` が「pyscard is not installed」または「No PC/SC reader detected」を出してスキップする(他機能は動く)

## セットアップ / 起動スクリプト

シェルスクリプト経由でセットアップ・起動できる. 詳細は `host/README.md`.

- `setup_all.sh` … ホスト一括 (`setup_apt.sh` → `setup_python.sh` → `setup_nfc.sh`). systemd 登録は含まない
- `run.sh` … `host/.venv/bin/uvicorn` ラッパー. 起動時に `host/.env` を読む. `HOST` / `PORT` 環境変数で上書き可. stdout/stderr を `tee` で `run.log`(`LOG_FILE` で変更可)に追記する. `run.log` / `*.log` は `.gitignore` 済み
- `test.sh` … 開発用モックサーバ(`host/scripts/mock_server.py`)起動ラッパー. 実機もバックエンドも不要で Web UI を確認できる
- `host/scripts/install_service.sh` … systemd 登録 + `enable --now`. 自動起動は明示的に分離している
- `pico/scripts/setup.sh` / `flash.sh` … mpremote 導入と Pico 書き込み. dev マシン or RPi5 のどちらでも実行可
- `pico-edge-reader/scripts/setup.sh` / `flash.sh` … 汎用 Pico ファーム用. `pico/scripts/*` と同等で対象が `pico-edge-reader/main.py`

新しくスクリプトを追加するときは:

- shebang `#!/usr/bin/env bash` + `set -euo pipefail`
- 冪等にする(再実行で壊れない)
- sudo が必要かどうかを最初に明示し、不適切な権限なら `exit 1`
- `host/scripts/*.sh` は `PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"` で host ルートを取得する流儀

## Git / コミット規約

- **言語**: コミットメッセージは日本語. 過去ログ (`git log`) のスタイルを真似る(件名: 何をしたか1行、本文: 必要なら箇条書きで列挙)
- **末尾**: AI を使った場合は `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` を最後の行に付ける
- **粒度**: 機能変更とノイズ差分(改行コード正規化、純粋なフォーマット変更等)は **別コミットに分ける**. レビュー時のシグナルノイズ比を上げるため
- **ステージング**: `git add -A` / `git add .` は使わない. 必要なファイルを明示的に列挙する(`.env` 等の事故防止)
- **pre-commit hook**: 失敗したら `--no-verify` で抜けず、原因を直して **新規コミットを作る**(`--amend` ではない. amend は前のコミットを破壊する)
- **改行コード**: LF 固定. `.gitattributes` で `*.sh` / `*.py` / `*.md` 等を `eol=lf` に強制している. Windows エディタが CRLF を混入させても commit 時に LF へ正規化される

CLI からは HEREDOC で安全にメッセージを渡す:

```bash
git commit -m "$(cat <<'EOF'
件名(日本語、簡潔に)

- 変更点 1
- 変更点 2

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```
