# pico/ — Raspberry Pi Pico 側

Raspberry Pi Pico (MicroPython) に書き込むファームウェア. パチスロ実機のドライ接点出力を GPIO で読み取り、HIGH→LOW 立ち下がりエッジでイベント名を USB シリアルに 1 行ずつ出力します.

**このディレクトリの内容はラズパイ5には不要です.** Pico に直接書き込みます.

## 構成

```text
pico/
├── main.py     # 本体(MicroPython)
└── README.md
```

## 書き込み手順

1. Pico に MicroPython を書き込む([公式手順](https://www.raspberrypi.com/documentation/microcontrollers/micropython.html))
2. `main.py` を Pico のルートにコピー
   - Thonny: ファイルを開いて「Raspberry Pi Pico に保存」
   - mpremote: `mpremote cp main.py :main.py`
3. Pico を再起動すると自動的に実行され、`READY` を出力

## 配線

| パチスロ側 | Pico |
|---|---|
| COM | GND |
| IN  | GP2 |
| OUT | GP3 |
| RB  | GP4 |
| BB  | GP5 |

- 内部プルアップで通常 HIGH、信号 ON で LOW (active low)
- デバウンス 20ms

## 出力フォーマット

イベント発生ごとに `IN` / `OUT` / `RB` / `BB` のいずれかが 1 行で出力されます.

```
READY
IN
IN
BB
OUT
```

ラズパイ5側の `host/app/serial_reader.py` がこれを受信して SQLite に記録します.

## 動作確認(ラズパイ5なしで)

PC に Pico を接続し、シリアルターミナルで `/dev/ttyACM0` (Linux) や `COM3` (Windows) を 115200bps で開けば出力を確認できます.

```bash
screen /dev/ttyACM0 115200
# または
minicom -D /dev/ttyACM0 -b 115200
```
