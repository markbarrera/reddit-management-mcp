"""Shared pytest fixtures.

Sets REDDIT_DB_PATH before any project module is imported, since db.py
calls init_db() as an import-time side effect. Every test that touches
the database gets a fresh, isolated SQLite file via the tmp_db fixture.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("REDDIT_DB_PATH", "/tmp/reddit_mcp_test_import_time.db")
os.environ.setdefault("ANTHROPIC_API_KEY", "sk-test-not-a-real-key")

import pytest

import db as db_module


@pytest.fixture
def tmp_db(tmp_path, monkeypatch):
    """Point db.py at a fresh SQLite file and initialize its schema.

    Use this for any test that calls db.* functions — never rely on the
    shared import-time DB_PATH, since tests must not see each other's data.
    """
    path = str(tmp_path / "test.db")
    monkeypatch.setattr(db_module, "DB_PATH", path)
    db_module.init_db()
    yield db_module
