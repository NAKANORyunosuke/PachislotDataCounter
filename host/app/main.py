import asyncio
import io
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .db import (
    complete_registration,
    count_by_type,
    count_by_type_for_user,
    events_for_session,
    get_connection,
    get_display_settings,
    get_session,
    get_user_by_id,
    get_user_by_token,
    init_db,
    sessions_for_user,
    set_display_settings,
)
from .events import broadcaster
from .game_counter import game_counter
from .nfc_reader import run_nfc_reader
from .serial_reader import run_reader
from .session_manager import session_manager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SERIAL_PORT = os.environ.get("SERIAL_PORT", "/dev/ttyACM0")
SERIAL_BAUD = int(os.environ.get("SERIAL_BAUD", "115200"))
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

EVENT_KEYS = ("IN", "OUT", "BB", "RB")


def _snapshot() -> dict:
    with get_connection() as conn:
        counts = count_by_type(conn)
    snap: dict = {k: counts.get(k, 0) for k in EVENT_KEYS}
    snap["game_count"] = game_counter.game_count
    snap["in_renchan_zone"] = game_counter.in_renchan_zone
    return snap


def _zero_counts() -> dict[str, int]:
    return {k: 0 for k in EVENT_KEYS}


def _build_register_url(token: str, request: Request | None = None) -> str:
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}/register?token={token}"
    if request is not None:
        return str(request.url_for("register_page")) + f"?token={token}"
    return f"/register?token={token}"


def _build_settings_url(user_id: int, request: Request | None = None) -> str:
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL}/settings?user={user_id}"
    if request is not None:
        return str(request.url_for("settings_page")) + f"?user={user_id}"
    return f"/settings?user={user_id}"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    game_counter.seed_from_db()
    tasks = [
        asyncio.create_task(run_reader(SERIAL_PORT, SERIAL_BAUD)),
        asyncio.create_task(run_nfc_reader()),
    ]
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("Background task error during shutdown")


app = FastAPI(lifespan=lifespan)


@app.get("/api/counts")
def get_counts() -> dict:
    return _snapshot()


@app.get("/api/events/stream")
async def stream_events() -> StreamingResponse:
    async def gen():
        yield f"event: snapshot\ndata: {json.dumps(_snapshot())}\n\n"
        async for message in broadcaster.subscribe():
            yield f"event: event\ndata: {message}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/users/{user_id}/history")
def user_history(user_id: int) -> dict:
    with get_connection() as conn:
        user = get_user_by_id(conn, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        totals = count_by_type_for_user(conn, user_id)
        history = sessions_for_user(conn, user_id, limit=100)
    return {
        "user": {
            "id": user["id"],
            "name": user["name"],
            "registered": bool(user["registered"]),
            "card_idm": user["card_idm"],
        },
        "totals": {k: totals.get(k, 0) for k in EVENT_KEYS},
        "sessions": history,
    }


@app.get("/api/sessions/{session_id}")
def session_detail(session_id: int) -> dict:
    with get_connection() as conn:
        session = get_session(conn, session_id)
        if session is None:
            raise HTTPException(status_code=404, detail="session not found")
        events = events_for_session(conn, session_id)
        user = get_user_by_id(conn, session["user_id"])
    counts = _zero_counts()
    for ev in events:
        if ev["type"] in counts:
            counts[ev["type"]] += 1
    return {
        "session": session,
        "user": {
            "id": user["id"] if user else None,
            "name": user["name"] if user else None,
        },
        "counts": counts,
        "events": events,
    }


@app.get("/api/register/{token}")
def get_registration(token: str) -> dict:
    with get_connection() as conn:
        user = get_user_by_token(conn, token)
    if user is None:
        raise HTTPException(status_code=404, detail="invalid token")
    return {
        "user_id": user["id"],
        "card_idm": user["card_idm"],
        "registered": bool(user["registered"]),
    }


@app.post("/api/register/{token}")
async def post_registration(token: str, name: str = Form(...)) -> dict:
    name = name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if len(name) > 64:
        raise HTTPException(status_code=400, detail="name too long")
    with get_connection() as conn:
        user = complete_registration(conn, token, name)
    if user is None:
        raise HTTPException(status_code=404, detail="invalid or used token")
    await broadcaster.publish(
        json.dumps(
            {
                "kind": "user_registered",
                "user_id": user["id"],
                "name": user["name"],
            }
        )
    )
    return {"user_id": user["id"], "name": user["name"]}


@app.get("/api/users/{user_id}/settings")
def get_user_settings(user_id: int) -> dict:
    with get_connection() as conn:
        user = get_user_by_id(conn, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        settings = get_display_settings(conn, user_id)
    return {"user_id": user_id, "name": user["name"], "display_settings": settings}


@app.post("/api/users/{user_id}/settings")
async def post_user_settings(user_id: int, request: Request) -> dict:
    body = await request.json()
    hidden = body.get("hidden_panels", [])
    if not isinstance(hidden, list) or not all(isinstance(x, str) for x in hidden):
        raise HTTPException(
            status_code=400, detail="hidden_panels must be a list of strings"
        )
    settings = {"hidden_panels": hidden}
    with get_connection() as conn:
        if get_user_by_id(conn, user_id) is None:
            raise HTTPException(status_code=404, detail="user not found")
        set_display_settings(conn, user_id, settings)
    # Push so a monitor with this user's session active re-applies immediately.
    await broadcaster.publish(
        json.dumps(
            {
                "kind": "settings_updated",
                "user_id": user_id,
                "display_settings": settings,
            }
        )
    )
    return {"user_id": user_id, "display_settings": settings}


@app.get("/api/qr")
def qr_code(token: str | None = None, user: int | None = None) -> Response:
    try:
        import qrcode  # type: ignore
    except ImportError:
        raise HTTPException(
            status_code=503, detail="qrcode library not installed"
        )
    if user is not None:
        url = _build_settings_url(user)
    elif token:
        url = _build_register_url(token)
    else:
        raise HTTPException(status_code=400, detail="token or user is required")
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


@app.get("/register", response_class=HTMLResponse, name="register_page")
def register_page() -> HTMLResponse:
    path = STATIC_DIR / "register.html"
    return HTMLResponse(path.read_text(encoding="utf-8"))


@app.get("/settings", response_class=HTMLResponse, name="settings_page")
def settings_page() -> HTMLResponse:
    path = STATIC_DIR / "settings.html"
    return HTMLResponse(path.read_text(encoding="utf-8"))


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
