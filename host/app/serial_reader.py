import asyncio
import json
import logging
from datetime import datetime, timezone

import serial
from serial.serialutil import SerialException

from .db import get_connection, insert_event
from .events import broadcaster
from .session_manager import session_manager

logger = logging.getLogger(__name__)

VALID_EVENTS = {"IN", "OUT", "RB", "BB"}


def parse_line(line: str) -> str | None:
    token = line.strip().upper()
    if not token:
        return None
    if token.startswith("EVENT:"):
        token = token.split(":", 1)[1].strip()
    return token if token in VALID_EVENTS else None


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


async def _read_loop(ser: serial.Serial) -> None:
    loop = asyncio.get_running_loop()
    while True:
        raw = await loop.run_in_executor(None, ser.readline)
        if not raw:
            continue
        line = raw.decode("utf-8", errors="replace")
        event_type = parse_line(line)
        if event_type is None:
            logger.debug("Ignored line: %r", line)
            continue
        ts = datetime.now(timezone.utc).isoformat()
        session_id = session_manager.active_session_id
        with get_connection() as conn:
            insert_event(conn, event_type, ts, session_id)
        payload = json.dumps(
            {"kind": "event", "type": event_type, "ts": ts, "session_id": session_id}
        )
        print(f"[{ts}] {event_type} session={session_id}", flush=True)
        await broadcaster.publish(payload)
