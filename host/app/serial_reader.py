import asyncio
import json
import logging
import time
from datetime import datetime, timezone

import serial
from serial.serialutil import SerialException

from .db import get_connection, insert_event
from .events import broadcaster
from .game_counter import game_counter
from .payout_tracker import payout_tracker
from .session_manager import session_manager

logger = logging.getLogger(__name__)

VALID_EVENTS = {"IN", "OUT", "RB", "BB"}
VALID_EDGES = {"FALL", "RISE"}


def parse_csv_line(line: str) -> tuple[int, int, str, str] | None:
    """Pico の CSV 行 `timestamp_ms,game_id,event,edge,seq` を分解する.

    (timestamp_ms, game_id, event, edge) を返す. `READY,...` ヘッダや壊れた行は None.
    """
    parts = line.strip().split(",")
    if len(parts) != 5:
        return None
    ts_ms, game_id, event, edge, _seq = parts
    event = event.upper()
    edge = edge.upper()
    if event not in VALID_EVENTS or edge not in VALID_EDGES:
        return None
    try:
        return int(ts_ms), int(game_id), event, edge
    except ValueError:
        return None


async def run_reader(port: str, baud: int = 115200) -> None:
    # Avoid spamming logs every 3s when the Pico is simply not connected:
    # warn once per distinct error, demote repeats to debug.
    last_error_msg: str | None = None
    while True:
        try:
            ser = serial.Serial(port, baud, timeout=0.5)
        except (SerialException, FileNotFoundError, OSError) as exc:
            msg = str(exc)
            if msg != last_error_msg:
                logger.warning(
                    "Cannot open %s: %s. Will keep retrying every 3s.", port, exc
                )
                last_error_msg = msg
            else:
                logger.debug("Still cannot open %s: %s", port, exc)
            await asyncio.sleep(3)
            continue
        logger.info("Opened serial port %s @ %d", port, baud)
        last_error_msg = None
        try:
            await _read_loop(ser)
        except SerialException as exc:
            logger.warning("Serial error: %s. Reconnecting.", exc)
        finally:
            ser.close()
        await asyncio.sleep(1)


async def _publish(messages: list[dict]) -> None:
    for msg in messages:
        await broadcaster.publish(json.dumps(msg))


async def _read_loop(ser: serial.Serial) -> None:
    loop = asyncio.get_running_loop()
    while True:
        raw = await loop.run_in_executor(None, ser.readline)
        # 空読みのたびにも呼ぶ: OUT が途切れて確定した払い出しを配信する.
        await _publish(payout_tracker.tick(time.monotonic()))
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace")
        parsed = parse_csv_line(line)
        if parsed is None:
            logger.debug("Ignored line: %r", line)
            continue
        ts_ms, game_id, event_type, edge = parsed

        # game_counter は FALL / RISE 両方を見て game_id とボーナス窓を追う.
        info = game_counter.on_pico_event(event_type, edge, game_id)
        # payout_tracker は OUT を払い出し単位に区切り、ボーナス合計も出す.
        await _publish(
            payout_tracker.feed(
                event_type, edge, ts_ms, time.monotonic(), info["total_games"]
            )
        )

        # DB 記録・event SSE はイベント本体である FALL のみ. RISE はパルス終端 /
        # ボーナス終了の通知で、game_counter / payout_tracker が状態更新に使う.
        if edge != "FALL":
            continue

        ts = datetime.now(timezone.utc).isoformat()
        session_id = session_manager.active_session_id
        with get_connection() as conn:
            insert_event(conn, event_type, ts, session_id)
        payload = {"kind": "event", "type": event_type, "ts": ts, "session_id": session_id}
        payload.update(info)
        print(f"[{ts}] {event_type} g{game_id} session={session_id}", flush=True)
        await broadcaster.publish(json.dumps(payload))
