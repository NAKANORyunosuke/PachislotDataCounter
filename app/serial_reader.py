import asyncio
import json
import logging
from datetime import datetime, timezone

import serial
from serial.serialutil import SerialException

from .db import get_connection, insert_event
from .events import broadcaster

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
    while True:
        try:
            logger.info("Opening serial port %s @ %d", port, baud)
            ser = serial.Serial(port, baud, timeout=0.5)
        except (SerialException, FileNotFoundError, OSError) as exc:
            logger.warning("Cannot open %s: %s. Retrying in 3s.", port, exc)
            await asyncio.sleep(3)
            continue
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
        with get_connection() as conn:
            insert_event(conn, event_type, ts)
        payload = json.dumps({"type": event_type, "ts": ts})
        print(f"[{ts}] {event_type}", flush=True)
        await broadcaster.publish(payload)
