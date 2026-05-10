"""Test-suite-wide fixtures.

Redirects the query-log DB to a per-session tmp file so tests that boot the
FastAPI app (which runs ``init_db`` on startup) and tests that drive the
``/chat`` endpoint don't write to the production ``logs/queries.db``.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def _isolate_query_log_db() -> None:
    tmpdir = tempfile.mkdtemp(prefix="metaboagent-test-")
    os.environ["LOG_DB_PATH"] = str(Path(tmpdir) / "queries.db")
    yield
