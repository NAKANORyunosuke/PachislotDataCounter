"""OUT パルスを「1 回の払い出し」に区切る — 各ゲーム / 各ボーナスの払い出し枚数用.

Pico の暫定 game_id は次ゲームのレバーオンで切られるため、払い出しが境界を
またいで滲む(game_id 別の OUT 数は不正確). 一方ホッパーの 1 ゲームぶんの
払い出しは連続して出(〜100ms 間隔)、ゲーム間には数秒空く. そこで OUT FALL を
時間ギャップ(PAYOUT_GAP_MS)で区切れば、1 かたまり = そのゲーム 1 回の払い出し.

かたまりの先頭 OUT はまだ次のレバーオン前(払い出しはリール停止後、次のレバー
オンはその後)なので、先頭 OUT 時点の total_games がその払い出しのゲーム.
これで「どのゲームがいくつ払い出したか」が滲みなしで確定できる.
"""
from __future__ import annotations

# OUT がこのミリ秒以上途切れたら 1 回の払い出し確定. ゲーム内の OUT は
# 〜100ms 間隔、ゲーム間の払い出しは 2.5 秒以上空くので、その中間に取る.
PAYOUT_GAP_MS = 1000


class PayoutTracker:
    def __init__(self) -> None:
        self._medals = 0              # 区切り中の払い出し枚数
        self._game = 0                # 先頭 OUT 時点の total_games(= そのゲーム)
        self._chunk_in_bonus = False  # その払い出しがボーナス中に始まったか
        self._last_out_ms: int | None = None   # 直近 OUT の Pico timestamp_ms
        self._last_out_at: float | None = None  # 直近 OUT のホスト時刻(monotonic)
        self._in_bonus = False        # ボーナスの払い出し合計を集計中か
        self._bonus_total = 0
        self._bonus_kind: str | None = None

    def feed(self, event: str, edge: str, ts_ms: int, host_now: float,
             total_games: int) -> list[dict]:
        """Pico の CSV 1 行を渡し、確定した SSE ペイロード(payout/bonus_result)を返す."""
        emit: list[dict] = []
        if event == "OUT" and edge == "FALL":
            if self._medals and self._last_out_ms is not None:
                diff = ts_ms - self._last_out_ms
                # diff < 0 は Pico の ticks_ms 折り返し -> 別の払い出し扱い.
                if diff < 0 or diff > PAYOUT_GAP_MS:
                    emit.append(self._close())
            if not self._medals:
                self._game = total_games
                self._chunk_in_bonus = self._in_bonus
            self._medals += 1
            self._last_out_ms = ts_ms
            self._last_out_at = host_now
        elif event in ("BB", "RB"):
            if edge == "FALL":
                if self._medals:
                    emit.append(self._close())
                self._in_bonus = True
                self._bonus_total = 0
                self._bonus_kind = event
            else:  # RISE: ボーナス終了. 開いている払い出しを締めて合計を確定.
                if self._medals:
                    emit.append(self._close())
                if self._in_bonus:
                    emit.append({
                        "kind": "bonus_result",
                        "bonus": self._bonus_kind,
                        "medals": self._bonus_total,
                    })
                    self._in_bonus = False
        return emit

    def tick(self, host_now: float) -> list[dict]:
        """OUT が来ないまま PAYOUT_GAP_MS 経過していたら払い出しを確定する."""
        if (
            self._medals
            and self._last_out_at is not None
            and (host_now - self._last_out_at) * 1000 > PAYOUT_GAP_MS
        ):
            return [self._close()]
        return []

    def _close(self) -> dict:
        payout = {
            "kind": "payout",
            "medals": self._medals,
            "game": self._game,
            "in_bonus": self._chunk_in_bonus,
        }
        # ボーナス中に始まった払い出しはボーナス合計に積む.
        if self._chunk_in_bonus and self._in_bonus:
            self._bonus_total += self._medals
        self._medals = 0
        self._last_out_ms = None
        self._last_out_at = None
        return payout


payout_tracker = PayoutTracker()
