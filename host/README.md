# host/ — Raspberry Pi 5 側

Raspberry Pi 5 上で動作する FastAPI サーバ一式. プロジェクトルートからは `host/` ディレクトリの中身だけがラズパイ5に必要です(Pico に書き込むコードは `../pico/` を参照).

## 構成

```text
host/
├── app/                  # FastAPI バックエンド
│   ├── main.py           #   エントリポイント、ルーティング
│   ├── db.py             #   SQLite (events / users / sessions)
│   ├── events.py         #   SSE ブロードキャスタ
│   ├── serial_reader.py  #   Pico からのシリアル受信
│   ├── nfc_reader.py     #   PaSoRi (nfcpy) ポーリング
│   └── session_manager.py#   カードタップでのセッション状態遷移
├── static/               # Web UI (HTML / CSS / JS)
│   ├── index.html
│   ├── style.css
│   ├── app.js
│   └── register.html     # 新規カード登録フォーム
├── data/                 # SQLite DB (events.db)
├── systemd/              # systemd ユニット
├── scripts/
│   ├── setup_apt.sh         # apt 依存 (libusb / pyenv ビルド依存等)
│   ├── setup_python.sh      # pyenv + Python 3.13.5 + venv + pip install
│   ├── setup_nfc.sh         # PaSoRi セットアップ
│   └── install_service.sh   # systemd 登録 + 起動
└── requirements.txt
```

## 必要環境

- **Python 3.13.5** (`.python-version` で固定. pyenv 等で揃えてください)
  - `pyproject.toml` の `requires-python` は `>=3.13`
- Raspberry Pi OS Bookworm 標準の Python 3.11 では動作しません. pyenv で 3.13.5 を導入してから venv を作成してください.

## セットアップ

### 一括 (推奨)

プロジェクトルートから:

```bash
bash setup_all.sh
```

`setup_apt.sh` → `setup_python.sh` → `setup_nfc.sh` を順に実行します.
systemd サービス登録は含まれません(後述).

### 個別実行

```bash
sudo bash host/scripts/setup_apt.sh         # apt 依存
bash       host/scripts/setup_python.sh     # pyenv + Python 3.13.5 + .venv + pip install
sudo bash  host/scripts/setup_nfc.sh        # PaSoRi (任意)
sudo bash  host/scripts/install_service.sh  # systemd 登録 + 起動 (任意)
```

手動で進めたい場合:

```bash
cd host
pyenv install 3.13.5
pyenv local 3.13.5     # .python-version が既に置いてあるので自動で選択されます
python -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### PaSoRi (IC カードリーダー) を使う場合

プロジェクトルートから:

```bash
sudo bash host/scripts/setup_nfc.sh
```

このスクリプトは以下を実施します.

- `libusb` のインストール
- `host/.venv` に `nfcpy` / `qrcode[pil]` 等を導入
- `/etc/udev/rules.d/99-pasori.rules` を作成
- カーネル NFC モジュール (`port100` / `nfc`) を blacklist
- 実行ユーザを `plugdev` グループに追加

完了後、PaSoRi を抜き差しするか再起動してください.

動作確認:

```bash
host/.venv/bin/python -m nfc
```

## 起動

プロジェクトルートから:

```bash
bash run.sh                          # 0.0.0.0:8000
bash run.sh --reload                 # dev auto-reload
HOST=127.0.0.1 PORT=8080 bash run.sh # バインド変更
```

`run.sh` は `host/.venv/bin/uvicorn app.main:app` を実行するラッパーです.
追加引数はそのまま uvicorn に渡ります.

ブラウザで `http://<RPi5 の IP>:8000/` を開く.

## systemd 登録

スクリプト経由(推奨):

```bash
sudo bash host/scripts/install_service.sh
```

手動の場合:

```bash
sudo cp host/systemd/pachislot-data-counter.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now pachislot-data-counter
```

## 環境変数

| 変数 | デフォルト | 説明 |
|---|---|---|
| `SERIAL_PORT` | `/dev/ttyACM0` | Pico の USB シリアルポート |
| `SERIAL_BAUD` | `115200` | ボーレート |
| `PUBLIC_BASE_URL` | (未設定) | QR コードに埋め込む登録 URL のベース. Cloudflare Tunnel など外部公開ホスト名を指定 |

`PUBLIC_BASE_URL` 未設定時はリクエスト元のホスト名で URL を構築します(LAN 内動作向け).

## セッションの仕組み

- カードをかざす → 新規セッション開始
- 同じカードを再度かざす → セッション終了 (`end_reason=same_card_retap`)
- 別カードをかざす → 旧セッション終了 + 新規セッション開始 (`end_reason=other_card`)
- 未登録カード初回 → 登録用 QR コードを Web 画面に表示

イベント(IN/OUT/BB/RB)は受信時のアクティブセッションに紐付けて記録されます.

## API

| パス | 説明 |
|---|---|
| `GET /api/counts` | 全体の累計カウント |
| `GET /api/events/stream` | SSE: スナップショット + ライブイベント |
| `GET /api/users/{id}/history` | ユーザーごとの累計 + セッション履歴 |
| `GET /api/sessions/{id}` | セッション詳細(イベント列含む) |
| `GET /api/register/{token}` | 登録トークンの情報取得 |
| `POST /api/register/{token}` | 登録(`name` フォームフィールド) |
| `GET /api/qr?token=...` | 登録用 QR コード PNG |
| `GET /register?token=...` | 登録フォーム HTML |
