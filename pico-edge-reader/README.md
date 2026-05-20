# pico-edge-reader/ — 汎用 GPIO 立ち下がり検出ファームウェア

Raspberry Pi Pico (MicroPython) を「GPIO の立ち下がりエッジを検出して USB シリアルへ 1 行送る装置」にするスタンドアロンのファームウェアです.

信号の意味を一切持たない汎用版なので、`main.py` 先頭の `PINS` を書き換えれば任意の用途に流用できます. 既定のピン割り当ては Pachislot データカウンターの配線(IN/OUT/RB/BB)に合わせてあります.

> このフォルダは Pico に直接書き込むコード専用です. ラズパイ5側(`host/`)とは独立しています.
> MicroPython で動くため、CPython 専用の構文・標準ライブラリは使えません.

## 構成

```text
pico-edge-reader/
├── main.py             # 本体(MicroPython)
├── scripts/
│   ├── setup.sh        # mpremote を pico-edge-reader/.venv に導入
│   └── flash.sh        # main.py を Pico に書き込み + soft reset
└── README.md
```

## 書き込み手順

1. Pico に MicroPython を書き込む([公式手順](https://www.raspberrypi.com/documentation/microcontrollers/micropython.html))
2. 書き込みツールを導入(初回のみ):
   ```bash
   bash pico-edge-reader/scripts/setup.sh
   ```
3. `main.py` を Pico に転送:
   ```bash
   bash pico-edge-reader/scripts/flash.sh              # 自動検出
   bash pico-edge-reader/scripts/flash.sh /dev/ttyACM0 # ポート明示
   ```
4. スクリプトが mpremote 経由で reset するので、その直後から `READY` が出力されます

手動でやる場合は Thonny で「Raspberry Pi Pico に保存」、または `mpremote cp main.py :main.py` でも同等です.

## 配線(既定)

| 信号源 | Pico |
|---|---|
| COM | GND |
| IN  | GP2 |
| OUT | GP3 |
| RB  | GP4 |
| BB  | GP5 |

- 内部プルアップで通常 HIGH、ドライ接点が GND に閉じると LOW (active low)
- HIGH→LOW の立ち下がりエッジで `PINS` のラベルを 1 行出力
- デバウンス 20ms(`DEBOUNCE_MS`)

## ピン割り当ての変更

`main.py` 先頭の `PINS` を編集します. `(ラベル, GPIO番号)` のタプルを並べるだけです.

```python
PINS = (
    ("DOOR", 6),
    ("COIN", 7),
)
```

ラベルがそのまま 1 行として出力されます.

## 出力フォーマット

起動時に `READY`、以降は立ち下がりエッジごとにラベルが 1 行ずつ出力されます.

```
READY
IN
IN
BB
OUT
```

## 動作確認

PC に Pico を接続し、シリアルターミナルで `/dev/ttyACM0` (Linux) や `COM3` (Windows) を 115200bps で開くと出力を確認できます.

```bash
screen /dev/ttyACM0 115200
# または
minicom -D /dev/ttyACM0 -b 115200
```
