import asyncio
import io
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .db import (
    build_session_series,
    complete_registration,
    count_by_type,
    count_by_type_for_user,
    count_by_type_for_session,
    events_for_session,
    events_for_window,
    get_connection,
    get_display_settings,
    get_session,
    get_user_by_id,
    get_user_by_token,
    init_db,
    parse_display_settings,
    sessions_for_user,
    set_display_settings,
    window_counts,
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
        snap["total_games"] = game_counter.total_games

        # 接続/再接続時にアクティブセッションを復元できるよう同梱する.
        # (session_counts は確率カードの即時表示用, session_game_count は
        #  sessionGameBase 復元用. スランプ系列は /api/sessions/{id}/series で別途取得)
        sid = session_manager.active_session_id
        if sid is not None:
            session = get_session(conn, sid)
            if session is not None:
                user = get_user_by_id(conn, session["user_id"])
                if user is not None:
                    session_counts = count_by_type_for_session(conn, sid)
                    row = conn.execute(
                        "SELECT COUNT(DISTINCT game_id) AS n FROM events "
                        "WHERE session_id = ? AND game_id IS NOT NULL",
                        (sid,),
                    ).fetchone()
                    session_game_count = int(row["n"]) if row else 0
                    snap["active_session"] = {
                        "session_id": sid,
                        "user": {
                            "id": user["id"],
                            "name": user["name"],
                            "registered": bool(user["registered"]),
                            "card_idm": user["card_idm"],
                            "display_settings": parse_display_settings(
                                user["display_settings"]
                            ),
                        },
                        "started_at": session["started_at"],
                        "session_counts": {
                            k: session_counts.get(k, 0) for k in EVENT_KEYS
                        },
                        "session_game_count": session_game_count,
                    }
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


def _ensure_labels_json() -> None:
    """labels.json が無ければ labels.json.example からコピーして作る.

    labels.json はユーザーが現地で言葉遣いを差し替えるためのファイルで、
    リポジトリでは追跡せず例ファイル (.example) だけ管理する.
    """
    target = STATIC_DIR / "labels.json"
    if target.exists():
        return
    sample = STATIC_DIR / "labels.json.example"
    if not sample.exists():
        logger.warning("labels.json.example が見つからないのでスキップ")
        return
    try:
        target.write_bytes(sample.read_bytes())
        logger.info("labels.json を labels.json.example から生成しました")
    except OSError as exc:
        logger.warning("labels.json の自動生成に失敗: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _ensure_labels_json()
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


def _today_start_iso() -> str:
    """ローカル日付 0 時を UTC ISO で返す(events.ts と比較するため)."""
    local_now = datetime.now().astimezone()
    midnight = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc).isoformat()


@app.get("/api/stats")
def get_stats(user_id: int | None = None) -> dict:
    """ヒーロー表示のスコープ用集計を返す.

    全体: 当日 (today) / 全期間 (all)
    ユーザー: 当日 (today_user) / 全期間 (all_user)  ※ user_id 指定時のみ
    """
    with get_connection() as conn:
        today_iso = _today_start_iso()
        result: dict = {
            "today": window_counts(conn, since_iso=today_iso),
            "all": window_counts(conn),
        }
        if user_id is not None:
            result["today_user"] = window_counts(
                conn, since_iso=today_iso, user_id=user_id
            )
            result["all_user"] = window_counts(conn, user_id=user_id)
    return result


@app.get("/api/slump")
def get_slump(scope: str, user_id: int | None = None) -> dict:
    """ヒーロー上のスランプグラフをスコープ別に再構成する.

    scope: user-today / user-all / all-today / all-all
    (user-session はライブデータでフロントが描くのでこのエンドポイントは使わない)
    """
    today_iso = _today_start_iso()
    scope_map: dict[str, tuple[str | None, bool]] = {
        "user-today": (today_iso, True),
        "user-all":   (None,      True),
        "all-today":  (today_iso, False),
        "all-all":    (None,      False),
    }
    if scope not in scope_map:
        return {"slump": [{"x": 0, "y": 0}]}
    since, needs_user = scope_map[scope]
    uid = user_id if needs_user else None
    if needs_user and uid is None:
        return {"slump": [{"x": 0, "y": 0}]}
    with get_connection() as conn:
        events = events_for_window(conn, since_iso=since, user_id=uid)
    slump = build_session_series(events).get("slump", [])
    # 長期窓ではポイントが膨らむのでダウンサンプル.
    # 始端/終端は保ち、中間を等間隔で間引く.
    MAX_POINTS = 1500
    if len(slump) > MAX_POINTS:
        step = max(1, len(slump) // MAX_POINTS)
        sampled = slump[::step]
        if sampled[-1] is not slump[-1]:
            sampled.append(slump[-1])
        slump = sampled
    return {"slump": slump}


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


@app.get("/api/sessions/{session_id}/series")
def session_series(session_id: int) -> dict:
    """過去セッションのスランプ / 払い出しグラフを再描画するための系列データ."""
    with get_connection() as conn:
        if get_session(conn, session_id) is None:
            raise HTTPException(status_code=404, detail="session not found")
        events = events_for_session(conn, session_id)
    return build_session_series(events)


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
    order = body.get("panel_order")
    if order is not None and (
        not isinstance(order, list) or not all(isinstance(x, str) for x in order)
    ):
        raise HTTPException(
            status_code=400, detail="panel_order must be a list of strings"
        )
    settings: dict = {"hidden_panels": hidden}
    if order is not None:
        settings["panel_order"] = order
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
