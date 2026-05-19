import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .db import count_by_type, get_connection, init_db
from .events import broadcaster
from .serial_reader import run_reader

SERIAL_PORT = os.environ.get("SERIAL_PORT", "/dev/ttyACM0")
SERIAL_BAUD = int(os.environ.get("SERIAL_BAUD", "115200"))

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

EVENT_KEYS = ("IN", "OUT", "BB", "RB")


def _snapshot() -> dict[str, int]:
    with get_connection() as conn:
        counts = count_by_type(conn)
    return {k: counts.get(k, 0) for k in EVENT_KEYS}


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    task = asyncio.create_task(run_reader(SERIAL_PORT, SERIAL_BAUD))
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan)


@app.get("/api/counts")
def get_counts() -> dict[str, int]:
    return _snapshot()


@app.get("/api/events/stream")
async def stream_events() -> StreamingResponse:
    async def gen():
        yield f"event: snapshot\ndata: {json.dumps(_snapshot())}\n\n"
        async for message in broadcaster.subscribe():
            yield f"event: event\ndata: {message}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
