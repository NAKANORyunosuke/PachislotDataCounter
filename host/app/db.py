import secrets
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "events.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ts         TEXT    NOT NULL,
    type       TEXT    NOT NULL,
    session_id INTEGER REFERENCES sessions(id)
);
CREATE INDEX IF NOT EXISTS idx_events_ts         ON events(ts);
CREATE INDEX IF NOT EXISTS idx_events_type       ON events(type);
CREATE INDEX IF NOT EXISTS idx_events_session_id ON events(session_id);

CREATE TABLE IF NOT EXISTS users (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    card_idm           TEXT    NOT NULL UNIQUE,
    name               TEXT,
    registered         INTEGER NOT NULL DEFAULT 0,
    registration_token TEXT    UNIQUE,
    created_at         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_card_idm           ON users(card_idm);
CREATE INDEX IF NOT EXISTS idx_users_registration_token ON users(registration_token);

CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL REFERENCES users(id),
    started_at TEXT    NOT NULL,
    ended_at   TEXT,
    end_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user_id    ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_started_at ON sessions(started_at);
"""

LEGACY_MIGRATIONS = [
    # Older builds may have events without session_id.
    ("events", "session_id", "ALTER TABLE events ADD COLUMN session_id INTEGER REFERENCES sessions(id)"),
]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _ensure_columns(conn: sqlite3.Connection) -> None:
    for table, column, ddl in LEGACY_MIGRATIONS:
        cols = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            conn.execute(ddl)
    conn.commit()


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone()
    return row is not None


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        # Run column migrations on any pre-existing tables before re-running
        # the full schema (CREATE INDEX on a missing column would fail).
        if _table_exists(conn, "events"):
            _ensure_columns(conn)
        conn.executescript(SCHEMA)
        _ensure_columns(conn)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------


def insert_event(
    conn: sqlite3.Connection,
    event_type: str,
    ts: str | None = None,
    session_id: int | None = None,
) -> int:
    ts = ts or _now_iso()
    cur = conn.execute(
        "INSERT INTO events (ts, type, session_id) VALUES (?, ?, ?)",
        (ts, event_type, session_id),
    )
    conn.commit()
    return cur.lastrowid


def count_by_type(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute("SELECT type, COUNT(*) AS n FROM events GROUP BY type").fetchall()
    return {row["type"]: row["n"] for row in rows}


def count_by_type_for_session(conn: sqlite3.Connection, session_id: int) -> dict[str, int]:
    rows = conn.execute(
        "SELECT type, COUNT(*) AS n FROM events WHERE session_id = ? GROUP BY type",
        (session_id,),
    ).fetchall()
    return {row["type"]: row["n"] for row in rows}


def count_by_type_for_user(conn: sqlite3.Connection, user_id: int) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT e.type, COUNT(*) AS n
        FROM events e
        JOIN sessions s ON s.id = e.session_id
        WHERE s.user_id = ?
        GROUP BY e.type
        """,
        (user_id,),
    ).fetchall()
    return {row["type"]: row["n"] for row in rows}


def events_for_session(conn: sqlite3.Connection, session_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT id, ts, type FROM events WHERE session_id = ? ORDER BY id ASC",
        (session_id,),
    ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------


def get_user_by_idm(conn: sqlite3.Connection, card_idm: str) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE card_idm = ?", (card_idm,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(conn: sqlite3.Connection, user_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def get_user_by_token(conn: sqlite3.Connection, token: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM users WHERE registration_token = ?", (token,)
    ).fetchone()
    return dict(row) if row else None


def create_user_for_card(conn: sqlite3.Connection, card_idm: str) -> dict:
    token = secrets.token_urlsafe(16)
    cur = conn.execute(
        """
        INSERT INTO users (card_idm, registered, registration_token, created_at)
        VALUES (?, 0, ?, ?)
        """,
        (card_idm, token, _now_iso()),
    )
    conn.commit()
    return get_user_by_id(conn, cur.lastrowid)  # type: ignore[return-value]


def complete_registration(conn: sqlite3.Connection, token: str, name: str) -> dict | None:
    user = get_user_by_token(conn, token)
    if user is None:
        return None
    conn.execute(
        """
        UPDATE users
           SET name = ?, registered = 1, registration_token = NULL
         WHERE id = ?
        """,
        (name.strip(), user["id"]),
    )
    conn.commit()
    return get_user_by_id(conn, user["id"])


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


def start_session(conn: sqlite3.Connection, user_id: int) -> dict:
    ts = _now_iso()
    cur = conn.execute(
        "INSERT INTO sessions (user_id, started_at) VALUES (?, ?)",
        (user_id, ts),
    )
    conn.commit()
    return {
        "id": cur.lastrowid,
        "user_id": user_id,
        "started_at": ts,
        "ended_at": None,
        "end_reason": None,
    }


def end_session(conn: sqlite3.Connection, session_id: int, reason: str) -> dict | None:
    ts = _now_iso()
    conn.execute(
        "UPDATE sessions SET ended_at = ?, end_reason = ? WHERE id = ? AND ended_at IS NULL",
        (ts, reason, session_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def get_session(conn: sqlite3.Connection, session_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    return dict(row) if row else None


def sessions_for_user(conn: sqlite3.Connection, user_id: int, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        """
        SELECT s.id, s.started_at, s.ended_at, s.end_reason,
               COALESCE(SUM(CASE WHEN e.type='IN'  THEN 1 ELSE 0 END), 0) AS in_count,
               COALESCE(SUM(CASE WHEN e.type='OUT' THEN 1 ELSE 0 END), 0) AS out_count,
               COALESCE(SUM(CASE WHEN e.type='BB'  THEN 1 ELSE 0 END), 0) AS bb_count,
               COALESCE(SUM(CASE WHEN e.type='RB'  THEN 1 ELSE 0 END), 0) AS rb_count
          FROM sessions s
          LEFT JOIN events e ON e.session_id = s.id
         WHERE s.user_id = ?
         GROUP BY s.id
         ORDER BY s.started_at DESC
         LIMIT ?
        """,
        (user_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]
