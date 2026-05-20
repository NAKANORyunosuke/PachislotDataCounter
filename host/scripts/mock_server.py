#!/usr/bin/env python3
"""開発用モックサーバ.

実機 (Pico) も FastAPI バックエンドも無しで host/static/ の Web UI を動かし、
演出・スランプグラフ・セッション表示を目視確認するためのもの.
依存ゼロ (Python 標準ライブラリのみ) なので .venv のパッケージ導入は不要.

使い方:
    python3 host/scripts/mock_server.py        # ポート 8000
    PORT=9000 python3 host/scripts/mock_server.py
    -> 表示された URL をブラウザで開く

/api/events/stream で擬似的なパチスロ稼働 (セッション開始 -> IN/OUT/BB/RB
-> セッション終了) を SSE で延々と流す. 本物の app.js がそれを受けて描画する.
"""
import json
import os
import random
import time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
PORT = int(os.environ.get("PORT", "8000"))

# loadUserHistory が叩く /api/users/{id}/history 用のダミー履歴.
FAKE_HISTORY = {
    "user": {"id": 1, "name": "テスト太郎", "registered": True, "card_idm": "0123456789ABCDEF"},
    "totals": {"IN": 12000, "OUT": 12450, "BB": 28, "RB": 19},
    "sessions": [
        {"id": 3, "started_at": "2026-05-19T10:00:00+00:00", "ended_at": "2026-05-19T12:30:00+00:00",
         "end_reason": "same_card_retap", "in_count": 4200, "out_count": 4800, "bb_count": 11, "rb_count": 6},
        {"id": 2, "started_at": "2026-05-18T14:00:00+00:00", "ended_at": "2026-05-18T16:00:00+00:00",
         "end_reason": "same_card_retap", "in_count": 3900, "out_count": 3600, "bb_count": 8, "rb_count": 7},
        {"id": 1, "started_at": "2026-05-17T09:00:00+00:00", "ended_at": "2026-05-17T11:00:00+00:00",
         "end_reason": "other_card", "in_count": 3900, "out_count": 4050, "bb_count": 9, "rb_count": 6},
    ],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, *args):
        pass  # アクセスログは静かに

    def do_GET(self):
        if self.path.startswith("/api/events/stream"):
            self._stream()
        elif self.path.startswith("/api/users/"):
            self._json(FAKE_HISTORY)
        elif self.path.startswith("/api/counts"):
            self._json({"IN": 0, "OUT": 0, "BB": 0, "RB": 0})
        else:
            super().do_GET()

    def _json(self, obj) -> None:
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self._simulate()
        except (BrokenPipeError, ConnectionResetError):
            pass  # ブラウザを閉じた / リロードした

    def _sse(self, event: str, data: dict) -> None:
        self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()

    def _emit(self, payload: dict) -> None:
        self._sse("event", payload)

    def _ev(self, etype: str, sid: int) -> None:
        self._emit({"kind": "event", "type": etype, "ts": now_iso(), "session_id": sid})

    def _simulate(self) -> None:
        self._sse("snapshot", {"IN": 0, "OUT": 0, "BB": 0, "RB": 0})
        sid = 0
        while True:
            sid += 1
            self._emit({
                "kind": "session_start", "session_id": sid, "started_at": now_iso(),
                "user": {"id": 1, "name": "テスト太郎", "registered": True},
            })
            for _ in range(random.randint(60, 160)):
                for _ in range(3):  # 1 ゲーム = 3 枚投入
                    self._ev("IN", sid)
                    time.sleep(0.04)
                roll = random.random()
                if roll < 0.05:  # ボーナス当選
                    bonus = random.choice(["BB", "RB"])
                    self._ev(bonus, sid)
                    payout = random.randint(150, 330) if bonus == "BB" else random.randint(70, 120)
                    for _ in range(payout):
                        self._ev("OUT", sid)
                        time.sleep(0.008)
                elif roll < 0.4:  # 小役払い出し
                    for _ in range(random.randint(2, 14)):
                        self._ev("OUT", sid)
                        time.sleep(0.02)
                time.sleep(0.2)
            self._emit({"kind": "session_end", "session_id": sid, "ended_at": now_iso()})
            time.sleep(2.5)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Mock server: http://localhost:{PORT}  (Ctrl+C で停止)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
