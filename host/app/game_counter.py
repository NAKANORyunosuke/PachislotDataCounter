"""直近ボーナスからのゲーム数を数える — 連チャン演出のための土台.

ゲーム数の専用信号は無いため IN パルスから推定する. 1 ゲーム分の賭けメダルは
短時間に連続して入る(クレジット+MAXBET なら一瞬, 手入れでも 1 秒未満)一方,
ゲーム間にはリール回転ぶんの間隔(規定のウェイトで 4 秒以上)が空く. そこで
IN パルスを時間ギャップで区切り 1 かたまり = 1 ゲームとして数える. これで
通常の 3 枚がけ / ジャグラーのペカリ後の 1 枚がけ を賭け枚数に関係なく扱える.

連チャン = 直近ボーナスから RENCHAN_LIMIT ゲーム以内の次のボーナス当選.
"""
from __future__ import annotations

from datetime import datetime

from .db import get_connection

# 同一ゲームの賭けメダルはこの秒数以内に連続して入る. これより空いたら次ゲーム.
IN_BURST_GAP_SEC = 2.5
# 連チャン判定およびゾーン表示の上限ゲーム数.
RENCHAN_LIMIT = 100


class GameCounter:
    def __init__(self) -> None:
        self._games = 0
        self._last_in_ts: datetime | None = None
        self._had_bonus = False

    @property
    def game_count(self) -> int:
        return self._games

    @property
    def in_renchan_zone(self) -> bool:
        return self._had_bonus and self._games <= RENCHAN_LIMIT

    def on_event(self, event_type: str, ts: datetime) -> dict:
        """1 イベントぶん状態を更新し、SSE ペイロードに足すフィールドを返す."""
        if event_type == "IN":
            if (
                self._last_in_ts is None
                or (ts - self._last_in_ts).total_seconds() >= IN_BURST_GAP_SEC
            ):
                self._games += 1
            self._last_in_ts = ts
        elif event_type in ("BB", "RB"):
            won_at = self._games
            renchan = self._had_bonus and won_at <= RENCHAN_LIMIT
            self._games = 0
            self._last_in_ts = None
            self._had_bonus = True
            return {
                "game_count": 0,
                "in_renchan_zone": True,
                "renchan": renchan,
                "win_game_count": won_at,
            }
        return {"game_count": self._games, "in_renchan_zone": self.in_renchan_zone}

    def seed_from_db(self) -> None:
        """保存済みイベントから状態を復元し、再起動でゲーム数が飛ばないようにする."""
        with get_connection() as conn:
            last_bonus = conn.execute(
                "SELECT id FROM events WHERE type IN ('BB','RB') ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self._had_bonus = last_bonus is not None
            after_id = last_bonus["id"] if last_bonus else 0
            in_rows = conn.execute(
                "SELECT ts FROM events WHERE type = 'IN' AND id > ? ORDER BY id ASC",
                (after_id,),
            ).fetchall()
        games = 0
        last_ts: datetime | None = None
        for row in in_rows:
            ts = datetime.fromisoformat(row["ts"])
            if last_ts is None or (ts - last_ts).total_seconds() >= IN_BURST_GAP_SEC:
                games += 1
            last_ts = ts
        self._games = games
        self._last_in_ts = last_ts


game_counter = GameCounter()
