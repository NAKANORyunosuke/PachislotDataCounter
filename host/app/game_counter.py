"""直近ボーナスからのゲーム数を数える — 連チャン演出のための土台.

ゲーム数の専用信号は無いため IN パルスから推定する. IN はレバーON 時に賭け枚数
ぶんまとまって出る(リプレイの自動再ベットも IN を出す)一方、ゲーム間にはリール
回転ぶんの間隔が空く. そこで IN パルスを時間ギャップ(IN_BURST_GAP_SEC)で区切り、
1 かたまり = 1 ゲームとして数える. これで通常の 3 枚がけ / ジャグラーのペカリ後の
1 枚がけ、さらにリプレイゲームも、賭け枚数・種別に依存せず数えられる.

連チャン = 直近ボーナスから RENCHAN_LIMIT ゲーム以内の次のボーナス当選.

ボーナス中もベットして IN が出るため、放っておくとボーナス中のゲームも数えて
しまう. host/config.json の bonus_games(BB/RB 別のボーナス1回あたりゲーム数)を
設定すると、ボーナス当選時にカウントを -bonus_games から始める. するとボーナス中は
表示ゲーム数が 0、ボーナス終了あたりで 1 から数え直す(0 のままなら従来どおり
ボーナス中も加算). 外部に見せる値は負値を 0 でクランプする.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .db import get_connection

# 同一ゲームの賭けメダルはこの秒数以内に連続して入る. これより空いたら次ゲーム.
IN_BURST_GAP_SEC = 2.5
# 連チャン判定およびゾーン表示の上限ゲーム数.
RENCHAN_LIMIT = 100

CONFIG_PATH = Path(__file__).resolve().parent.parent / "config.json"


class GameCounter:
    def __init__(self) -> None:
        self._games = 0          # 直近ボーナスからのゲーム数(ボーナス中は負値)
        self._total_games = 0    # 起動以降の累計ゲーム数(スランプグラフの X 軸用)
        self._last_in_ts: datetime | None = None
        self._had_bonus = False
        # ボーナス 1 回を何ゲームとみなしてカウントから差し引くか(BB/RB 別).
        self._bonus_games = {"BB": 0, "RB": 0}

    def load_config(self) -> None:
        """host/config.json を読む. 無い / 壊れている場合は既定値のまま."""
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                cfg = json.load(f)
        except (OSError, ValueError):
            return
        bonus = cfg.get("bonus_games") if isinstance(cfg, dict) else None
        if isinstance(bonus, dict):
            for key in ("BB", "RB"):
                try:
                    self._bonus_games[key] = max(0, int(bonus.get(key, 0)))
                except (TypeError, ValueError):
                    pass

    @property
    def game_count(self) -> int:
        return max(0, self._games)  # ボーナス中は負側にあるので 0 でクランプ

    @property
    def total_games(self) -> int:
        return self._total_games

    @property
    def in_renchan_zone(self) -> bool:
        return self._had_bonus and self.game_count <= RENCHAN_LIMIT

    def _info(self) -> dict:
        return {
            "game_count": self.game_count,
            "in_renchan_zone": self.in_renchan_zone,
            "total_games": self._total_games,
        }

    def on_event(self, event_type: str, ts: datetime) -> dict:
        """1 イベントぶん状態を更新し、SSE ペイロードに足すフィールドを返す."""
        if event_type == "IN":
            if (
                self._last_in_ts is None
                or (ts - self._last_in_ts).total_seconds() >= IN_BURST_GAP_SEC
            ):
                self._games += 1
                self._total_games += 1
            self._last_in_ts = ts
        elif event_type in ("BB", "RB"):
            won_at = self.game_count
            renchan = self._had_bonus and won_at <= RENCHAN_LIMIT
            self._games = -self._bonus_games.get(event_type, 0)
            self._last_in_ts = None
            self._had_bonus = True
            return {**self._info(), "renchan": renchan, "win_game_count": won_at}
        return self._info()

    def seed_from_db(self) -> None:
        """保存済みイベントから状態を復元し、再起動でゲーム数が飛ばないようにする.

        load_config() の後に呼ぶこと(bonus_games を使うため).
        """
        with get_connection() as conn:
            last_bonus = conn.execute(
                "SELECT id, type FROM events WHERE type IN ('BB','RB') "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
            self._had_bonus = last_bonus is not None
            after_id = last_bonus["id"] if last_bonus else 0
            in_rows = conn.execute(
                "SELECT ts FROM events WHERE type = 'IN' AND id > ? ORDER BY id ASC",
                (after_id,),
            ).fetchall()
        bonus_type = last_bonus["type"] if last_bonus else None
        games = -self._bonus_games.get(bonus_type, 0) if bonus_type else 0
        last_ts: datetime | None = None
        for row in in_rows:
            ts = datetime.fromisoformat(row["ts"])
            if last_ts is None or (ts - last_ts).total_seconds() >= IN_BURST_GAP_SEC:
                games += 1
            last_ts = ts
        self._games = games
        self._last_in_ts = last_ts
        self._total_games = max(0, games)


game_counter = GameCounter()
