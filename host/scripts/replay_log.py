#!/usr/bin/env python3
"""Pico の CSV ログを Web UI に流して再生する開発ツール.

実機 (Pico) も FastAPI バックエンドも無しで、渡された Pico の生ログを host の
本物のロジック(game_counter / payout_tracker)に通し、結果を SSE で配信する.
ブラウザで開けば、そのログがそのまま Web UI(演出・スランプ・払い出し・
ゲーム数・連チャン)に再生される.

使い方:
    再生したい Pico ログを host/scripts/replay.log に置いて:
        python3 host/scripts/replay_log.py
    別ファイルを再生するなら引数で渡す:
        python3 host/scripts/replay_log.py <Pico ログのパス>
    -> 表示された URL をブラウザで開く

セッション単位のパネル(スランプ・払い出し)を表示させるため、ログ全体を
1 つの合成セッションで包んで配信する.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

HOST_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = HOST_DIR / "static"
sys.path.insert(0, str(HOST_DIR))  # app パッケージ(game_counter / payout_tracker)用

from app.game_counter import GameCounter
from app.payout_tracker import PayoutTracker

PORT = int(os.environ.get("PORT", "8000"))
# 再生するログ. 引数で渡すか、既定の host/scripts/replay.log を置く(.gitignore 済み).
DEFAULT_LOG = Path(__file__).resolve().parent / "replay.log"
LOG_PATH = sys.argv[1] if len(sys.argv) > 1 else str(DEFAULT_LOG)
MAX_GAP_SEC = 2.0  # ログ内の長い空き時間はこの秒数まで詰めて再生

VALID_EVENTS = {"IN", "OUT", "RB", "BB"}
VALID_EDGES = {"FALL", "RISE"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_csv_line(line: str):
    """Pico CSV 行 timestamp_ms,game_id,event,edge,seq -> (ts_ms, game_id, event, edge)."""
    parts = line.strip().split(",")
    if len(parts) != 5:
        return None
    ts_ms, game_id, event, edge, _seq = parts
    event, edge = event.upper(), edge.upper()
    if event not in VALID_EVENTS or edge not in VALID_EDGES:
        return None
    try:
        return int(ts_ms), int(game_id), event, edge
    except ValueError:
        return None


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, *args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/events/stream":
            self._stream()
        elif path == "/api/qr":
            self._placeholder_qr()
        elif path == "/settings":
            self._serve("settings.html")
        else:
            super().do_GET()  # 静的ファイル(/api/users/... は 404 でも無害)

    def _placeholder_qr(self) -> None:
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220">'
            '<rect width="220" height="220" fill="#fff"/>'
            '<text x="110" y="115" text-anchor="middle" font-size="16">log replay</text>'
            "</svg>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(svg)))
        self.end_headers()
        self.wfile.write(svg)

    def _serve(self, name: str) -> None:
        body = (STATIC_DIR / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send(self, event: str, data: dict) -> None:
        self.wfile.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            self._replay()
            # 再生後は接続を保ったまま(EventSource の再接続で再生し直さない)
            while True:
                time.sleep(60)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _replay(self) -> None:
        """ログを host の本物のロジックに通して SSE 配信する."""
        gc, pt = GameCounter(), PayoutTracker()
        self._send("snapshot", {
            "IN": 0, "OUT": 0, "BB": 0, "RB": 0,
            "game_count": 0, "in_renchan_zone": False, "total_games": 0,
        })
        # 合成セッション: セッション単位パネル(スランプ・払い出し)を出すため.
        self._send("event", {
            "kind": "session_start", "session_id": 1, "started_at": now_iso(),
            "user": {"id": 1, "name": "ログ再生", "registered": True,
                     "display_settings": {}},
        })
        last_ts = None
        host_now = 0.0
        for raw in open(LOG_PATH, encoding="utf-8"):
            parsed = parse_csv_line(raw)
            if parsed is None:
                continue  # READY ヘッダや空行
            ts_ms, game_id, event, edge = parsed
            if last_ts is not None:
                gap = (ts_ms - last_ts) / 1000.0
                if gap > 0:
                    time.sleep(min(gap, MAX_GAP_SEC))
            last_ts = ts_ms
            host_now = ts_ms / 1000.0

            info = gc.on_pico_event(event, edge, game_id)
            for msg in pt.feed(event, edge, ts_ms, host_now, info["total_games"]):
                self._send("event", msg)
            if edge != "FALL":
                continue
            payload = {"kind": "event", "type": event, "ts": now_iso(),
                       "session_id": 1}
            payload.update(info)
            self._send("event", payload)
        # 末尾の払い出しを締める
        for msg in pt.tick(host_now + 10):
            self._send("event", msg)
        self._send("event", {"kind": "session_end", "session_id": 1,
                             "ended_at": now_iso()})


def main() -> None:
    if not Path(LOG_PATH).is_file():
        print(f"ログが見つかりません: {LOG_PATH}", file=sys.stderr)
        raise SystemExit(1)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Log replay: http://localhost:{PORT}  (log={LOG_PATH}, Ctrl+C で停止)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
