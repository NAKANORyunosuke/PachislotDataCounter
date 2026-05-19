# CLAUDE.md

このリポジトリで作業する際の Claude 向けガイド.

## プロジェクト概要

家スロ用データカウンター. Raspberry Pi Pico がパチスロ実機のドライ接点出力(IN/OUT/RB/BB)を GPIO で読み取り USB シリアルで Raspberry Pi 5 に送信、RPi5 上の FastAPI が SQLite に記録し Web UI と SSE で配信する.

PaSoRi RC-S380 を RPi5 に接続し、IC カードでユーザー識別とセッション管理ができる.

## ディレクトリ構造(重要)

`host/` と `pico/` は **完全に独立した別ターゲット** のコードです. 混在させないこと.

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
└── pico/         # Raspberry Pi Pico (MicroPython)
    └── main.py
```

- ラズパイ5に置くのは `host/` 配下のみ.
- `pico/main.py` は **MicroPython** で動く. CPython の構文や標準ライブラリを前提にしないこと(`asyncio`, `pathlib`, `typing` などは使えない).
- 何かを編集するとき、対象がどちらのターゲットかを最初に意識する.

## 必要環境

- **Python 3.13.5**(`host/.python-version` で固定. `pyproject.toml` の `requires-python` は `>=3.13`)
- Raspberry Pi OS Bookworm 標準の 3.11 では動かない. pyenv で 3.13.5 を入れる前提.

## よく使うコマンド

すべて `host/` 配下から実行:

```bash
cd host
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000   # 開発起動
.venv/bin/python -c "from app.db import init_db; init_db()"  # DB マイグレーション
.venv/bin/python -m nfc                                       # PaSoRi 認識確認
sudo bash scripts/setup_nfc.sh                                # PaSoRi 初期設定(プロジェクトルートから sudo bash host/scripts/setup_nfc.sh でも可)
```

## アーキテクチャ要点

### 並行タスク
`host/app/main.py` の lifespan で 2 つの asyncio タスクが走る:
- `run_reader` (`serial_reader.py`): Pico からの USB シリアルを read、イベントを DB と SSE に流す
- `run_nfc_reader` (`nfc_reader.py`): nfcpy で PaSoRi を別スレッド (run_in_executor) でポーリング、タップを `session_manager.handle_tap` に流す

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
`PUBLIC_BASE_URL` 環境変数(Cloudflare Tunnel 等の公開ホスト名)があればそれを使う. 未設定時はリクエスト元のホスト名で組み立てる. systemd の Environment 行で指定.

### SSE イベント形式
クライアントは EventSource で `/api/events/stream` を購読. 内部メッセージは `kind` フィールドで判別:
- `event` … パチスロイベント(IN/OUT/BB/RB)
- `session_start` / `session_end`
- `register_required` / `user_registered`

初回接続時のみ別 SSE event 名 `snapshot` で累計カウントを送る.

### DB スキーマ
`host/data/events.db` (SQLite). `host/app/db.py` の `SCHEMA` 定数に DDL がまとまっている. レガシー DB(`session_id` 列がない `events`)は `init_db()` 時に自動 ALTER で吸収.

```
events    (id, ts, type, session_id)
users     (id, card_idm UNIQUE, name, registered, registration_token, created_at)
sessions  (id, user_id, started_at, ended_at, end_reason)
```

## コーディング規約

- Python 標準ライブラリと PEP 604 (`str | None`) / PEP 585 (`dict[str, int]`) を使う(3.13 前提).
- 過剰な抽象化や将来要件のためのレイヤーを足さない. シンプルさ優先.
- コメントは「なぜ」を残す目的のみ. 何をしているかは識別子で表現する.
- 既存のスタイルに揃える(`host/app/` の各モジュールがリファレンス).
- フロントは生 JS + Chart.js(CDN). フレームワーク導入はしない方針.

## やってはいけないこと

- `pico/main.py` に CPython 専用構文を持ち込む(MicroPython 互換が壊れる).
- `host/.venv/` をリポジトリにコミットする(`.gitignore` 済み).
- `host/data/events.db` をコミットする(`.gitignore` 済み).
- 既存 DB に対する破壊的マイグレーション. 必要なら `db.py` の `LEGACY_MIGRATIONS` に追加して `init_db` で安全に適用.
- 認証や個人情報を扱う前提の機能拡張(個人利用想定なのでスコープ外).

## テスト

現状ユニットテストはない. 動作確認は:

1. `host/.venv/bin/python -c "from app.main import app; print([r.path for r in app.routes])"` でルート登録を確認
2. `.venv/bin/uvicorn app.main:app` で起動し `curl http://localhost:8000/api/counts`
3. PaSoRi がない環境では `nfc_reader` が「nfcpy not installed / NFC reader not available」を出してスキップする(他機能は動く)
