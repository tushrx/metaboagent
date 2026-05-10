"""Tests for app.query_log — anonymous SQLite query logger."""
from __future__ import annotations

import asyncio
import json
import pathlib
import sqlite3

import pytest

from app.query_log import _resolve_db_path, init_db, log_query


@pytest.fixture
def db_path(tmp_path: pathlib.Path) -> str:
    return str(tmp_path / "queries.db")


def _read_indexes(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='index' AND tbl_name='queries'"
        )
        return {r[0] for r in cur.fetchall()}
    finally:
        conn.close()


def _last_row(db_path: str) -> tuple:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT timestamp_utc, user_email, user_query, tier, demo_mode, "
            "tools_called, tool_count, response_length, duration_ms, "
            "status, error_message, remote_ip "
            "FROM queries ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()


def test_init_db_creates_table_and_indexes(db_path: str) -> None:
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='queries'"
        )
        assert cur.fetchone() is not None
    finally:
        conn.close()
    indexes = _read_indexes(db_path)
    assert "idx_queries_timestamp" in indexes
    assert "idx_queries_user_email" in indexes
    assert "idx_queries_status" in indexes


def test_init_db_is_idempotent(db_path: str) -> None:
    init_db(db_path)
    init_db(db_path)
    init_db(db_path)
    # Should still have exactly one queries table.
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type='table' AND name='queries'"
        )
        assert cur.fetchone()[0] == 1
    finally:
        conn.close()


def test_log_query_inserts_row_with_all_fields(db_path: str) -> None:
    init_db(db_path)
    record = {
        "timestamp_utc": "2026-05-10T15:30:00Z",
        "user_email": "alice@example.com",
        "user_query": "What is glucose?",
        "tier": "default",
        "demo_mode": False,
        "tools_called": ["search_kegg", "fetch_pubchem"],
        "tool_count": 2,
        "response_length": 350,
        "duration_ms": 1234,
        "status": "ok",
        "error_message": None,
        "remote_ip": "203.0.113.1",
    }
    asyncio.run(log_query(record, db_path))
    row = _last_row(db_path)
    assert row[0] == "2026-05-10T15:30:00Z"
    assert row[1] == "alice@example.com"
    assert row[2] == "What is glucose?"
    assert row[3] == "default"
    assert row[4] == 0
    assert json.loads(row[5]) == ["search_kegg", "fetch_pubchem"]
    assert row[6] == 2
    assert row[7] == 350
    assert row[8] == 1234
    assert row[9] == "ok"
    assert row[10] is None
    assert row[11] == "203.0.113.1"


def test_log_query_handles_none_user_email_and_empty_tools(db_path: str) -> None:
    init_db(db_path)
    record = {
        "timestamp_utc": "2026-05-10T15:30:00Z",
        "user_email": None,
        "user_query": "anonymous",
        "tier": "default",
        "demo_mode": True,
        "tools_called": [],
        "tool_count": 0,
        "response_length": 100,
        "duration_ms": 500,
        "status": "ok",
        "error_message": None,
        "remote_ip": None,
    }
    asyncio.run(log_query(record, db_path))
    row = _last_row(db_path)
    assert row[1] is None
    assert row[4] == 1
    assert json.loads(row[5]) == []
    assert row[11] is None


def test_log_query_swallows_db_errors(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    bad_path = str(tmp_path / "no_such_dir" / "queries.db")
    record = {
        "timestamp_utc": "2026-05-10T15:30:00Z",
        "user_email": None,
        "user_query": "test",
        "tier": "default",
        "demo_mode": False,
        "tools_called": [],
        "tool_count": 0,
        "response_length": None,
        "duration_ms": 1,
        "status": "ok",
        "error_message": None,
        "remote_ip": None,
    }
    with caplog.at_level("WARNING", logger="app.query_log"):
        asyncio.run(log_query(record, bad_path))
    assert any(
        "query_log_write_failed" in r.getMessage() for r in caplog.records
    )


def test_init_db_swallows_errors(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # Path where the parent path is a file, not a directory — mkdir fails.
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("file in the way")
    bad_path = str(blocker / "queries.db")
    with caplog.at_level("WARNING", logger="app.query_log"):
        init_db(bad_path)
    assert any(
        "query_log_init_failed" in r.getMessage() for r in caplog.records
    )


def test_resolve_db_path_priority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOG_DB_PATH", raising=False)
    assert _resolve_db_path("/foo/bar.db") == "/foo/bar.db"
    monkeypatch.setenv("LOG_DB_PATH", "/baz.db")
    assert _resolve_db_path(None) == "/baz.db"
    monkeypatch.delenv("LOG_DB_PATH")
    assert _resolve_db_path(None) == "logs/queries.db"
