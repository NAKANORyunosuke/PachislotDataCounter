"""PaSoRi RC-S380 polling loop using nfcpy.

Runs in a background thread (nfcpy is blocking) and dispatches tap events to
the asyncio session manager via run_coroutine_threadsafe.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from .session_manager import session_manager

logger = logging.getLogger(__name__)

# Cooldown between accepted taps from the same card, to avoid spamming the
# session manager while a card sits on the reader.
TAP_COOLDOWN_SEC = 1.5

# nfcpy device path. The "usb" form lets libusb pick any supported reader.
NFC_DEVICE = "usb"


def _format_idm(tag) -> Optional[str]:
    idm = getattr(tag, "identifier", None)
    if not idm:
        return None
    return idm.hex().upper()


async def run_nfc_reader() -> None:
    try:
        import nfc  # type: ignore
    except ImportError:
        logger.warning(
            "nfcpy is not installed. NFC reader disabled. "
            "Install with: pip install nfcpy"
        )
        return

    loop = asyncio.get_running_loop()
    last_idm: Optional[str] = None
    last_ts = 0.0

    def on_connect(tag) -> bool:
        nonlocal last_idm, last_ts
        idm = _format_idm(tag)
        if idm is None:
            logger.debug("Tag without identifier: %r", tag)
            return False
        now = time.monotonic()
        if idm == last_idm and (now - last_ts) < TAP_COOLDOWN_SEC:
            return False
        last_idm = idm
        last_ts = now
        logger.info("Card tapped idm=%s", idm)
        asyncio.run_coroutine_threadsafe(session_manager.handle_tap(idm), loop)
        # Return False so nfcpy returns immediately without waiting for release.
        return False

    def _poll_forever() -> None:
        # Reconnect outer loop in case the reader is unplugged mid-run.
        while True:
            try:
                with nfc.ContactlessFrontend(NFC_DEVICE) as clf:
                    logger.info("NFC reader ready: %s", clf)
                    while True:
                        clf.connect(
                            rdwr={
                                "on-connect": on_connect,
                                "beep-on-connect": False,
                            }
                        )
            except IOError as exc:
                logger.warning("NFC reader not available (%s). Retrying in 3s.", exc)
                time.sleep(3)
            except Exception:
                logger.exception("Unexpected NFC reader error. Retrying in 3s.")
                time.sleep(3)

    await loop.run_in_executor(None, _poll_forever)
