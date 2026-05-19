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
│   └── setup_nfc.sh      # PaSoRi セットアップ
└── requirements.txt
```

## セットアップ

```bash
cd host
python3 -m venv .venv
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

開発時:

```bash
cd host
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

ブラウザで `http://<RPi5 の IP>:8000/` を開く.

## systemd 登録

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
