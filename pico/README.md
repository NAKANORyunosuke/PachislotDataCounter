# pico/ — Raspberry Pi Pico 側

Raspberry Pi Pico (MicroPython) に書き込むファームウェア. パチスロ実機のドライ接点出力を GPIO で読み取り、HIGH→LOW 立ち下がりエッジでイベント名を USB シリアルに 1 行ずつ出力します.

**このディレクトリの内容はラズパイ5には不要です.** Pico に直接書き込みます.

## 構成

```text
pico/
├── main.py             # 本体(MicroPython)
├── scripts/
│   ├── setup.sh        # mpremote を pico/.venv に導入
│   └── flash.sh        # main.py を Pico に書き込み + soft reset
└── README.md
```

## 書き込み手順

1. Pico に MicroPython を書き込む([公式手順](https://www.raspberrypi.com/documentation/microcontrollers/micropython.html))
2. 書き込みツールを導入(初回のみ):
   ```bash
   bash pico/scripts/setup.sh
   ```
3. `main.py` を Pico に転送:
   ```bash
   bash pico/scripts/flash.sh             # 自動検出
   bash pico/scripts/flash.sh /dev/ttyACM0 # ポート明示
   ```
4. スクリプトが mpremote 経由で reset するので、その直後から `READY` が出力されます

手動でやる場合は Thonny で「Raspberry Pi Pico に保存」、または `mpremote cp main.py :main.py` でも同等です.

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
