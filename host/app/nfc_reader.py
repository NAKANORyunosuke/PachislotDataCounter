"""IC card reader via PC/SC (pyscard).

Works with any CCID-compliant reader registered with the system pcscd daemon —
notably PaSoRi RC-S300 (USB 054c:0dc9), which nfcpy does not support. Runs the
blocking PC/SC poll loop in a background thread and dispatches tap events to
the asyncio session manager via run_coroutine_threadsafe.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from .session_manager import session_manager

logger = logging.getLogger(__name__)

# Re-tap cooldown for the *same* IDm. Card-removed events reset this anyway.
TAP_COOLDOWN_SEC = 1.5
POLL_INTERVAL_SEC = 0.3

# PC/SC "GET DATA" APDU — CCID readers return the card UID/IDm here.
APDU_GET_UID = [0xFF, 0xCA, 0x00, 0x00, 0x00]


async def run_nfc_reader() -> None:
    try:
        from smartcard.System import readers
        from smartcard.Exceptions import (
            CardConnectionException,
            NoCardException,
            NoReadersException,
        )
    except ImportError:
        logger.warning(
            "pyscard is not installed. NFC reader disabled. "
            "Install with: pip install pyscard (apt: libpcsclite-dev pcscd)"
        )
        return

    loop = asyncio.get_running_loop()
    last_idm: Optional[str] = None
    last_ts = 0.0

    def dispatch(idm: str) -> None:
        nonlocal last_idm, last_ts
        if not idm:
            return
        now = time.monotonic()
        if idm == last_idm and (now - last_ts) < TAP_COOLDOWN_SEC:
            return
        last_idm = idm
        last_ts = now
        logger.info("Card tapped idm=%s", idm)
        asyncio.run_coroutine_threadsafe(session_manager.handle_tap(idm), loop)

    def _poll_forever() -> None:
        # Track the IDm of the card currently sitting on the reader so we only
        # fire one tap per physical presentation; the cooldown above is a
        # belt-and-braces guard against detection chatter.
        present_idm: Optional[str] = None

        while True:
            try:
                rs = readers()
            except NoReadersException:
                rs = []
            if not rs:
                logger.warning(
                    "No PC/SC reader detected. Is pcscd running? Retrying in 3s."
                )
                time.sleep(3)
                continue

            reader = rs[0]
            logger.info("PC/SC reader ready: %s", reader)

            try:
                while True:
                    conn = reader.createConnection()
                    try:
                        conn.connect()
                        recv, sw1, sw2 = conn.transmit(APDU_GET_UID)
                        if sw1 == 0x90 and sw2 == 0x00:
                            idm = bytes(recv).hex().upper()
                            if idm != present_idm:
                                present_idm = idm
                                dispatch(idm)
                        else:
                            logger.debug("APDU SW=%02X%02X", sw1, sw2)
                    except NoCardException:
                        present_idm = None
                    except CardConnectionException:
                        present_idm = None
                    finally:
                        try:
                            conn.disconnect()
                        except Exception:
                            pass
                    time.sleep(POLL_INTERVAL_SEC)
            except Exception:
                logger.exception(
                    "PC/SC reader loop crashed (unplugged?). Retrying in 3s."
                )
                present_idm = None
                time.sleep(3)

    await loop.run_in_executor(None, _poll_forever)
