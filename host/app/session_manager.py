"""Tracks the currently active session and handles card-tap state transitions.

Tap rules:
- No active session                -> start a new session for the tapped card
- Active session, same card        -> end (reason: same_card_retap)
- Active session, different card   -> end old (reason: other_card), start new
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from .db import (
    count_by_type_for_session,
    create_user_for_card,
    end_session,
    get_user_by_idm,
    get_connection,
    parse_display_settings,
    sessions_for_user,
    start_session,
)
from .events import broadcaster

logger = logging.getLogger(__name__)

PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")


def _registration_url(token: str) -> str:
    base = PUBLIC_BASE_URL or ""
    return f"{base}/register?token={token}"


class SessionManager:
    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._active_session_id: Optional[int] = None
        self._active_user_id: Optional[int] = None
        self._active_card_idm: Optional[str] = None

    @property
    def active_session_id(self) -> Optional[int]:
        return self._active_session_id

    async def handle_tap(self, card_idm: str) -> None:
        """Process a card tap event. All DB writes happen under the manager lock."""

        async with self._lock:
            with get_connection() as conn:
                user = get_user_by_idm(conn, card_idm)
                if user is None:
                    user = create_user_for_card(conn, card_idm)
                    logger.info(
                        "New card detected idm=%s user_id=%s", card_idm, user["id"]
                    )
                    await broadcaster.publish(
                        json.dumps(
                            {
                                "kind": "register_required",
                                "user_id": user["id"],
                                "token": user["registration_token"],
                                "register_url": _registration_url(
                                    user["registration_token"]
                                ),
                            }
                        )
                    )

                if (
                    self._active_session_id is not None
                    and self._active_card_idm == card_idm
                ):
                    await self._end_active(conn, "same_card_retap")
                    return

                if self._active_session_id is not None:
                    await self._end_active(conn, "other_card")

                session = start_session(conn, user["id"])
                self._active_session_id = session["id"]
                self._active_user_id = user["id"]
                self._active_card_idm = card_idm
                history = sessions_for_user(conn, user["id"], limit=20)

            await broadcaster.publish(
                json.dumps(
                    {
                        "kind": "session_start",
                        "session_id": session["id"],
                        "user": {
                            "id": user["id"],
                            "name": user["name"],
                            "registered": bool(user["registered"]),
                            "card_idm": card_idm,
                            "display_settings": parse_display_settings(
                                user["display_settings"]
                            ),
                        },
                        "started_at": session["started_at"],
                        "history": history,
                    }
                )
            )
            logger.info(
                "Session %s started for user_id=%s", session["id"], user["id"]
            )

    async def _end_active(self, conn, reason: str) -> None:
        if self._active_session_id is None:
            return
        sid = self._active_session_id
        uid = self._active_user_id
        ended = end_session(conn, sid, reason)
        counts = count_by_type_for_session(conn, sid)
        self._active_session_id = None
        self._active_user_id = None
        self._active_card_idm = None
        await broadcaster.publish(
            json.dumps(
                {
                    "kind": "session_end",
                    "session_id": sid,
                    "user_id": uid,
                    "ended_at": ended["ended_at"] if ended else None,
                    "end_reason": reason,
                    "counts": counts,
                }
            )
        )
        logger.info("Session %s ended (%s)", sid, reason)


session_manager = SessionManager()
