"""Anonymous SQLite query logging for /chat requests.

Each successful or failed /chat request appends one row to ``logs/queries.db``
capturing (timestamp, query, tier, tools_called, response_length,
duration_ms, status). Logging is fire-and-forget — DB failures are
swallowed and warned, never block /chat.

The ``user_email`` column is reserved nullable for a later auth integration.
422 validation errors from Pydantic do NOT reach this logger because they
are rejected before the chat handler runs.

Sample reporting queries::

    -- Total queries today
    SELECT COUNT(*) FROM queries WHERE timestamp_utc >= date('now');

    -- Queries by hour (last 24)
    SELECT strftime('%Y-%m-%d %H:00', timestamp_utc) AS hour, COUNT(*)
    FROM queries GROUP BY hour ORDER BY hour DESC LIMIT 24;

    -- Error rate
    SELECT status, COUNT(*) FROM queries GROUP BY status;

    -- Slowest queries
    SELECT substr(user_query, 1, 60), duration_ms, tool_count
    FROM queries ORDER BY duration_ms DESC LIMIT 10;
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_DB_PATH = "logs/queries.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS queries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp_utc TEXT NOT NULL,
    user_email TEXT,
    user_query TEXT NOT NULL,
    tier TEXT,
    demo_mode INTEGER NOT NULL,
    tools_called TEXT,
    tool_count INTEGER NOT NULL,
    response_length INTEGER,
    duration_ms INTEGER NOT NULL,
    status TEXT NOT NULL,
    error_message TEXT,
    remote_ip TEXT
);
CREATE INDEX IF NOT EXISTS idx_queries_timestamp ON queries(timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_queries_user_email ON queries(user_email);
CREATE INDEX IF NOT EXISTS idx_queries_status ON queries(status);
"""


def _resolve_db_path(path: str | None = None) -> str:
    return path or os.environ.get("LOG_DB_PATH") or DEFAULT_DB_PATH


def init_db(path: str | None = None) -> None:
    """Create the ``queries`` table + indexes if they don't exist. Idempotent.

    Creates the parent directory if missing. Failures are logged and
    swallowed so a bad path can't crash app startup.
    """
    db_path = _resolve_db_path(path)
    try:
        parent = os.path.dirname(db_path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(_SCHEMA)
            conn.commit()
        finally:
            conn.close()
    except Exception as exc:
        log.warning("query_log_init_failed db=%s err=%s", db_path, exc)


def _insert_sync(db_path: str, record: dict[str, Any]) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """INSERT INTO queries (
                timestamp_utc, user_email, user_query, tier, demo_mode,
                tools_called, tool_count, response_length, duration_ms,
                status, error_message, remote_ip
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record["timestamp_utc"],
                record.get("user_email"),
                record["user_query"],
                record.get("tier"),
                int(bool(record.get("demo_mode", False))),
                json.dumps(record.get("tools_called") or []),
                int(record.get("tool_count", 0)),
                record.get("response_length"),
                int(record["duration_ms"]),
                record["status"],
                record.get("error_message"),
                record.get("remote_ip"),
            ),
        )
        conn.commit()
    finally:
        conn.close()


async def log_query(record: dict[str, Any], path: str | None = None) -> None:
    """Append one row. Fire-and-forget — never raises.

    The actual SQLite write runs in a thread executor so it doesn't block
    the event loop. Any DB error is logged at WARNING and swallowed.
    """
    db_path = _resolve_db_path(path)
    try:
        await asyncio.to_thread(_insert_sync, db_path, record)
    except Exception as exc:
        log.warning("query_log_write_failed db=%s err=%s", db_path, exc)
