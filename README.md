# PachislotDataCounter

Raspberry Pi PicoとRaspberry Pi 5を用いた, 軽量なパチスロ用データカウンターシステム.

## 概要

本プロジェクトは, パチスロ実機の外部出力(IN / OUT / RB / BB などのドライ接点信号)をRaspberry Pi Pico の GPIO で読み取り, USBシリアル経由で Raspberry Pi 5へ送信するシステムです. 

Raspberry Pi 5側では, 
- データ集計
- リアルタイム表示
- ログ保存
- Webダッシュボード表示

などを行います. 

家スロ環境向けの, 軽量かつ拡張性の高いデータカウンター構築を目的としています. 

---

## システム構成

```text
パチスロ実機
    ↓
外部出力(ドライ接点)
    ↓
Raspberry Pi Pico
    ↓ USBシリアル
Raspberry Pi 5
    ↓
FastAPI Webアプリ
    ↓
ブラウザ表示
```

---

## 信号対応

| パチスロ側 | Pico GPIO |
|---|---|
| COM | GND |
| IN | GP2 |
| OUT | GP3 |
| RB | GP4 |
| BB | GP5|

---

## ドライ接点の動作

通常時：

```text
GPIO = HIGH (3.3V)
```

信号ON時：

```text
GPIO = LOW (0V)
```

(active low)

---

## 機能

- GPIOによる信号検出
- USBシリアル通信
- リアルタイムWeb表示
- イベントログ保存
- BB/RB統計
- 総回転数集計
- 軽量構成

---

## 実装予定

- 履歴グラフ表示
- OBSオーバーレイ
- Discord通知
- 複数台対応
- Grafana連携
- 設定推測補助

---

## ハードウェア構成

- Raspberry Pi 5
- Raspberry Pi Pico
- ブレッドボード
- ジャンパワイヤ
- テスター

---

## ソフトウェア構成

- Python
- FastAPI
- pyserial
- SQLite

---

## ディレクトリ構成

```text
PachislotDataCounter/
├── pico/          # Pico側コード
├── backend/       # FastAPIサーバ
├── frontend/      # Web UI
├── docs/          # 配線図・資料
└── README.md
```

---

## 注意

本プロジェクトは, 個人所有の実機を対象とした個人利用・学習用途を想定しています. 

---

## 開発状況

現在開発中(Work in Progress)

- [ ] 外部出力の検証
- [ ] Pico GPIO入力実装
- [ ] USBシリアル通信
- [ ] FastAPIバックエンド
- [ ] Web UI
- [ ] ログ保存