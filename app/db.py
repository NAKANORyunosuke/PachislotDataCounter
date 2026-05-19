import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "events.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    ts   TEXT    NOT NULL,
    type TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA)


def insert_event(conn: sqlite3.Connection, event_type: str, ts: str | None = None) -> int:
    ts = ts or datetime.now(timezone.utc).isoformat()
    cur = conn.execute("INSERT INTO events (ts, type) VALUES (?, ?)", (ts, event_type))
    conn.commit()
    return cur.lastrowid


def count_by_type(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT type, COUNT(*) AS n FROM events GROUP BY type").fetchall()
    return {row["type"]: row["n"] for row in rows}
