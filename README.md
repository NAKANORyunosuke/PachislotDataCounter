# PachislotDataCounter

Raspberry Pi PicoとRaspberry Pi 5を用いた, 軽量なパチスロ用データカウンターシステム.

## 概要

パチスロ実機の外部出力(IN / OUT / RB / BB のドライ接点信号)を Raspberry Pi Pico の GPIO で読み取り, USB シリアル経由で Raspberry Pi 5 へ送信するシステムです.

Raspberry Pi 5 側では,

- データ集計
- リアルタイム表示
- ログ保存
- Web ダッシュボード表示
- IC カード(PaSoRi)によるアカウント識別とセッション管理

を行います.

家スロ環境向けの, 軽量かつ拡張性の高いデータカウンター構築を目的としています.

---

## システム構成

```text
パチスロ実機
    ↓
外部出力(ドライ接点)
    ↓
Raspberry Pi Pico          <-- pico/  (MicroPython, Pico に書き込む)
    ↓ USBシリアル
Raspberry Pi 5             <-- host/  (FastAPI / SQLite / Web UI)
    ↓
ブラウザ表示
```

---

## ディレクトリ構成

```text
PachislotDataCounter/
├── host/             # Raspberry Pi 5 に置くもの (FastAPI サーバ一式)
│   ├── app/          #   FastAPI バックエンド (Python)
│   ├── static/       #   Web UI (HTML/CSS/JS)
│   ├── data/         #   SQLite DB ファイル (events.db)
│   ├── systemd/      #   systemd ユニット
│   ├── scripts/      #   セットアップスクリプト (PaSoRi 等)
│   ├── requirements.txt
│   └── README.md     #   ラズパイ5側の手順
├── pico/             # Raspberry Pi Pico に書き込むもの (MicroPython)
│   ├── main.py
│   └── README.md     #   Pico 側の手順
├── LICENSE
└── README.md         # このファイル (プロジェクト概要)
```

`host/` と `pico/` は完全に独立しています. **Raspberry Pi 5 には `host/` 配下だけがあれば動作します.** `pico/` は Pico に書き込むためのソースを管理する目的でリポジトリに同居しています.

---

## クイックスタート

### Raspberry Pi 5 側

詳細は [`host/README.md`](host/README.md) を参照.

```bash
cd host
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
sudo bash scripts/setup_nfc.sh         # PaSoRi を使う場合
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
```

### Raspberry Pi Pico 側

詳細は [`pico/README.md`](pico/README.md) を参照.

`pico/main.py` を MicroPython の入った Pico にコピーするだけです.

---

## 信号対応

| パチスロ側 | Pico GPIO |
|---|---|
| COM | GND |
| IN  | GP2 |
| OUT | GP3 |
| RB  | GP4 |
| BB  | GP5 |

通常時 `HIGH (3.3V)`, 信号 ON 時 `LOW (0V)` の active low.

---

## 機能

- GPIO による信号検出 (Pico)
- USB シリアル通信 (Pico → RPi5)
- リアルタイム Web 表示 (FastAPI + SSE)
- イベントログ保存 (SQLite)
- BB/RB 統計 / 総回転数集計
- IC カード(PaSoRi RC-S380)によるユーザー識別
- カードタップによるセッション管理
- 未登録カードの QR コード経由オンライン登録

---

## 実装予定

- OBS オーバーレイ
- Discord 通知
- 複数台対応
- Grafana 連携
- 設定推測補助

---

## ハードウェア構成

- Raspberry Pi 5
- Raspberry Pi Pico
- Sony PaSoRi RC-S380 (任意)
- ブレッドボード / ジャンパワイヤ / テスター

---

## 注意

本プロジェクトは, 個人所有の実機を対象とした個人利用・学習用途を想定しています.

---

## 開発状況

現在開発中 (Work in Progress)

- [x] FastAPI バックエンド
- [x] Web UI
- [x] ログ保存
- [x] IC カードによるセッション管理
- [ ] 外部出力の検証
- [ ] Pico GPIO 入力実装(`pico/main.py` で実装、実機検証中)
- [ ] USB シリアル通信
