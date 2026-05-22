#!/usr/bin/env python3
"""開発用モックサーバ.

実機 (Pico) も FastAPI バックエンドも無しで host/static/ の Web UI を動かし、
演出・スランプグラフ・セッション表示・表示プロファイルを目視確認するためのもの.
依存ゼロ (Python 標準ライブラリのみ) なので .venv のパッケージ導入は不要.

使い方:
    python3 host/scripts/mock_server.py        # ポート 8000
    PORT=9000 python3 host/scripts/mock_server.py
    -> 表示された URL をブラウザで開く

擬似的なパチスロ稼働を 1 本のスレッドで生成し、接続中の全クライアントへ SSE で
配信する. 設定フォーム (/settings) からの保存も settings_updated として全クライ
アントへ流れるので、モニタ側のレイアウト切替をその場で確認できる.
"""
import json
import os
import queue
import random
import threading
import time
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
PORT = int(os.environ.get("PORT", "8000"))

# 擬似ユーザー (id=1). 表示プロファイルは設定フォームからの保存で書き換わる.
FAKE_USER = {"id": 1, "name": "テスト太郎", "registered": True, "card_idm": "0123456789ABCDEF"}
FAKE_HISTORY_SESSIONS = [
    {"id": 3, "started_at": "2026-05-19T10:00:00+00:00", "ended_at": "2026-05-19T12:30:00+00:00",
     "end_reason": "same_card_retap", "in_count": 4200, "out_count": 4800, "bb_count": 11, "rb_count": 6},
    {"id": 2, "started_at": "2026-05-18T14:00:00+00:00", "ended_at": "2026-05-18T16:00:00+00:00",
     "end_reason": "same_card_retap", "in_count": 3900, "out_count": 3600, "bb_count": 8, "rb_count": 7},
    {"id": 1, "started_at": "2026-05-17T09:00:00+00:00", "ended_at": "2026-05-17T11:00:00+00:00",
     "end_reason": "other_card", "in_count": 3900, "out_count": 4050, "bb_count": 9, "rb_count": 6},
]

# user_id -> display_settings(dict). 設定フォーム POST で更新される.
_user_settings: dict[int, dict] = {}
# 接続中の SSE クライアント (それぞれ 1 本の Queue).
_clients: set[queue.Queue] = set()
_clients_lock = threading.Lock()
# 進行中セッションの session_start ペイロード. 途中接続のクライアントへ送り直す.
_active_session: dict | None = None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def broadcast(event: str, data: dict) -> None:
    """全 SSE クライアントへ 1 メッセージ送る."""
    chunk = f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()
    with _clients_lock:
        for q in _clients:
            q.put(chunk)


# 連チャン判定の上限ゲーム数 / 1 ゲームあたりのボーナス当選率(テストしやすい値).
RENCHAN_LIMIT = 100
BONUS_RATE = 0.015


def sim_loop() -> None:
    """擬似的なパチスロ稼働を延々と生成する (デーモンスレッド)."""
    global _active_session
    sid = 0
    games = 0          # 直近ボーナスからのゲーム数(機械全体, セッションをまたぐ)
    total = 0          # 起動以降の累計ゲーム数(スランプグラフ X 軸用)
    had_bonus = False
    while True:
        sid += 1
        _active_session = {
            "kind": "session_start", "session_id": sid, "started_at": now_iso(),
            "user": {**FAKE_USER, "display_settings": _user_settings.get(FAKE_USER["id"], {})},
        }
        broadcast("event", _active_session)
        for _ in range(random.randint(60, 160)):
            games += 1
            total += 1
            zone = had_bonus and games <= RENCHAN_LIMIT
            for _ in range(3):  # 1 ゲーム = 3 枚投入
                _emit_event("IN", sid, games, zone, total)
                time.sleep(0.04)
            roll = random.random()
            if roll < BONUS_RATE:  # ボーナス当選
                bonus = random.choice(["BB", "RB"])
                broadcast("event", {
                    "kind": "event", "type": bonus, "ts": now_iso(), "session_id": sid,
                    "game_count": 0, "in_renchan_zone": True,
                    "renchan": had_bonus and games <= RENCHAN_LIMIT,
                    "win_game_count": games, "total_games": total,
                })
                games = 0
                had_bonus = True
                # ボーナス中ゲーム: 各ゲーム 14 枚払い出し(連チャン数には入れない)
                bonus_total = 0
                for _ in range(random.randint(8, 16)):
                    total += 1
                    for _ in range(2):  # ボーナス中は 2 枚がけ
                        _emit_event("IN", sid, 0, True, total)
                        time.sleep(0.03)
                    for _ in range(14):
                        _emit_event("OUT", sid, 0, True, total)
                        time.sleep(0.01)
                    broadcast("event", {"kind": "payout", "medals": 14,
                                        "game": total, "in_bonus": True})
                    bonus_total += 14
                    time.sleep(0.15)
                broadcast("event", {"kind": "bonus_result", "bonus": bonus,
                                    "medals": bonus_total})
            elif roll < 0.4:  # 小役払い出し
                medals = random.randint(2, 14)
                for _ in range(medals):
                    _emit_event("OUT", sid, games, had_bonus and games <= RENCHAN_LIMIT, total)
                    time.sleep(0.02)
                broadcast("event", {"kind": "payout", "medals": medals,
                                    "game": total, "in_bonus": False})
            time.sleep(0.2)
        _active_session = None
        broadcast("event", {"kind": "session_end", "session_id": sid, "ended_at": now_iso()})
        time.sleep(2.5)


def _emit_event(etype: str, sid: int, games: int, zone: bool, total: int) -> None:
    broadcast("event", {
        "kind": "event", "type": etype, "ts": now_iso(), "session_id": sid,
        "game_count": games, "in_renchan_zone": zone, "total_games": total,
    })


def _fake_series(sid: int) -> dict:
    """過去セッションのスランプ / 払い出し系列を擬似生成(session_id で固定)."""
    rng = random.Random(sid)
    slump = [{"x": 0, "y": 0}]
    payout: list[dict] = []
    cum = 0
    for g in range(1, rng.randint(120, 350) + 1):
        cum -= 3  # 3 枚がけ
        roll = rng.random()
        if roll < 0.025:  # ボーナス級
            medals = rng.choice([96, 112, 240, 312])
            cum += medals
            payout.append({"game": g, "medals": medals})
        elif roll < 0.42:  # 小役
            medals = rng.randint(2, 15)
            cum += medals
            payout.append({"game": g, "medals": medals})
        slump.append({"x": g, "y": cum})
    return {"slump": slump, "payout": payout}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def log_message(self, *args):
        pass  # アクセスログは静かに

    # --- GET ---------------------------------------------------------------
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/events/stream":
            self._stream()
        elif path == "/api/qr":
            self._qr_placeholder()
        elif path == "/settings":
            self._serve_file("settings.html")
        elif path.startswith("/api/users/") and path.endswith("/settings"):
            uid = self._user_id_from_path(path)
            self._json({
                "user_id": uid, "name": FAKE_USER["name"],
                "display_settings": _user_settings.get(uid, {}),
            })
        elif path.startswith("/api/users/") and path.endswith("/history"):
            self._json({
                "user": FAKE_USER,
                "totals": {"IN": 12000, "OUT": 12450, "BB": 28, "RB": 19},
                "sessions": FAKE_HISTORY_SESSIONS,
            })
        elif path.startswith("/api/sessions/") and path.endswith("/series"):
            try:
                sid = int(path.split("/")[3])
            except (IndexError, ValueError):
                sid = 0
            self._json(_fake_series(sid))
        elif path == "/api/counts":
            self._json({"IN": 0, "OUT": 0, "BB": 0, "RB": 0})
        else:
            super().do_GET()

    # --- POST --------------------------------------------------------------
    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/api/users/") and path.endswith("/settings"):
            uid = self._user_id_from_path(path)
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._json({"detail": "invalid json"}, status=400)
                return
            hidden = body.get("hidden_panels", [])
            if not isinstance(hidden, list):
                self._json({"detail": "hidden_panels must be a list"}, status=400)
                return
            settings = {"hidden_panels": hidden}
            _user_settings[uid] = settings
            broadcast("event", {
                "kind": "settings_updated", "user_id": uid, "display_settings": settings,
            })
            self._json({"user_id": uid, "display_settings": settings})
        else:
            self._json({"detail": "not found"}, status=404)

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def _user_id_from_path(path: str) -> int:
        # /api/users/<id>/settings
        try:
            return int(path.split("/")[3])
        except (IndexError, ValueError):
            return 0

    def _json(self, obj, status: int = 200) -> None:
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_file(self, name: str) -> None:
        body = (STATIC_DIR / name).read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _qr_placeholder(self) -> None:
        # モックは qrcode ライブラリを持たないので、QR の代わりに目印画像を返す.
        # 実際のリンクは設定パネル/登録パネルの「リンクで開く」から辿れる.
        qs = parse_qs(urlparse(self.path).query)
        label = f"user={qs['user'][0]}" if "user" in qs else "register"
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="220" height="220">'
            '<rect width="220" height="220" fill="#fff"/>'
            '<text x="110" y="104" text-anchor="middle" font-size="18" fill="#000">QR (mock)</text>'
            f'<text x="110" y="132" text-anchor="middle" font-size="12" fill="#666">{label}</text>'
            "</svg>"
        ).encode()
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(svg)))
        self.end_headers()
        self.wfile.write(svg)

    def _stream(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        q: queue.Queue = queue.Queue()
        with _clients_lock:
            _clients.add(q)
        try:
            snap = f"event: snapshot\ndata: {json.dumps({'IN': 0, 'OUT': 0, 'BB': 0, 'RB': 0})}\n\n"
            self.wfile.write(snap.encode())
            # 途中接続なら進行中セッションを送り直す.
            if _active_session is not None:
                self.wfile.write(
                    f"event: event\ndata: {json.dumps(_active_session)}\n\n".encode()
                )
            self.wfile.flush()
            while True:
                self.wfile.write(q.get())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # ブラウザを閉じた / リロードした
        finally:
            with _clients_lock:
                _clients.discard(q)


def main() -> None:
    threading.Thread(target=sim_loop, daemon=True).start()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Mock server: http://localhost:{PORT}  (Ctrl+C で停止)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")


if __name__ == "__main__":
    main()
