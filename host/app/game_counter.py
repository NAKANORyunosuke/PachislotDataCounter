"""直近ボーナスからのゲーム数を数える — 連チャン演出のための土台.

Pico は CSV 生ログで各イベントに「暫定 game_id」を付けて送ってくる
(`pico/main.py` 参照). ホストはその game_id の変化で 1 ゲーム進んだと判断する
ので、時間ギャップによるゲーム区切り推定は通常運転では不要.

BB/RB はレベル信号で、Pico は FALL=ボーナス開始 / RISE=ボーナス終了 を送る.
これでボーナス中の窓が正確に分かるため、ボーナス中のゲームは連チャンの
ゲーム数に数えない(ボーナス当選で 0、ボーナス終了後の最初のゲームで 1).

連チャン = 直近ボーナスから RENCHAN_LIMIT ゲーム以内の次のボーナス当選.
"""
from __future__ import annotations

from datetime import datetime

from .db import get_connection

# 連チャン判定およびゾーン表示の上限ゲーム数.
RENCHAN_LIMIT = 100
# 再起動時の概算復元(seed_from_db)でのみ使う IN まとめ閾値(秒).
# 通常運転は Pico の game_id を使うので、これは DB から概算する時専用.
SEED_IN_GAP_SEC = 2.5


class GameCounter:
    def __init__(self) -> None:
        self._game_count = 0          # 直近ボーナス(終了)からのゲーム数
        self._total_games = 0         # 起動以降の累計ゲーム数(スランプグラフ X 軸)
        self._last_game_id: int | None = None
        self._in_bonus = False
        self._had_bonus = False

    @property
    def game_count(self) -> int:
        return self._game_count

    @property
    def total_games(self) -> int:
        return self._total_games

    @property
    def in_renchan_zone(self) -> bool:
        return self._had_bonus and self._game_count <= RENCHAN_LIMIT

    def _info(self) -> dict:
        return {
            "game_count": self._game_count,
            "in_renchan_zone": self.in_renchan_zone,
            "total_games": self._total_games,
        }

    def on_pico_event(self, event: str, edge: str, game_id: int) -> dict:
        """Pico の CSV 1 行ぶん状態を更新し、SSE ペイロードに足すフィールドを返す.

        FALL / RISE 両方で呼ぶこと(ボーナス窓の追跡に RISE も使う).
        """
        # 新ゲーム検出は FALL のみで行う. RISE は対応する FALL とペアになるよう
        # Pico が FALL 時の game_id を載せてくる(ゲーム境界をまたいだ古い値も
        # あり得る)ので、ゲーム数の進行には使わない. 起動後に最初に見た
        # game_id は進行中ゲームの可能性があるので基準採用のみでカウントしない.
        if edge == "FALL":
            if self._last_game_id is not None and game_id != self._last_game_id:
                self._total_games += 1
                # ボーナス中のゲームは連チャンのゲーム数には数えない.
                if not self._in_bonus:
                    self._game_count += 1
            self._last_game_id = game_id

        if event in ("BB", "RB"):
            if edge == "FALL":
                won_at = self._game_count
                renchan = self._had_bonus and won_at <= RENCHAN_LIMIT
                self._game_count = 0
                self._in_bonus = True
                self._had_bonus = True
                return {**self._info(), "renchan": renchan, "win_game_count": won_at}
            # RISE: ボーナス終了. 以降の新ゲームから再びカウントされる.
            self._in_bonus = False
        return self._info()

    def seed_from_db(self) -> None:
        """再起動時に DB から状態を概算復元する.

        DB には game_id を保存していないため、直近ボーナス以降の IN イベントを
        時刻ギャップでまとめた概算(ボーナス中ぶんを含む). 次のボーナス当選で
        正確な値に戻る.
        """
        with get_connection() as conn:
            last_bonus = conn.execute(
                "SELECT id FROM events WHERE type IN ('BB','RB') "
                "ORDER BY id DESC LIMIT 1"
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
            if last_ts is None or (ts - last_ts).total_seconds() >= SEED_IN_GAP_SEC:
                games += 1
            last_ts = ts
        self._game_count = games
        self._total_games = games


game_counter = GameCounter()
