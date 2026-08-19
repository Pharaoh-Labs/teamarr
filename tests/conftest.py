"""Shared fixtures for the teamarr test suite.

DB fixtures replace the per-file tmp-DB boilerplate (iua3.5): a temp-file
database initialized through the full startup path (init_db → migrations →
reconciliation → seed), plus a factory bound to it for code that takes a
``db_factory`` argument.

Shared fakes/factories live in tests/fakes.py (import them, they are not
fixtures).
"""

import pytest


@pytest.fixture
def db_path(tmp_path):
    """Path to a fully-initialized temp database (fresh per test)."""
    from teamarr.database.connection import init_db

    path = tmp_path / "test.db"
    init_db(path)
    return path


@pytest.fixture
def db_factory(db_path):
    """get_db-style context-manager factory bound to the temp database."""
    from teamarr.database.connection import get_db

    return lambda: get_db(db_path)


@pytest.fixture
def db_conn(db_path):
    """Persistent connection to the temp database (closed on teardown)."""
    from teamarr.database.connection import get_connection

    conn = get_connection(db_path)
    yield conn
    conn.close()
