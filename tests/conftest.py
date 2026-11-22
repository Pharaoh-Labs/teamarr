"""Shared fixtures for the teamarr test suite.

DB fixtures replace the per-file tmp-DB boilerplate (iua3.5): a temp-file
database initialized through the full startup path (init_db → migrations →
reconciliation → seed), plus a factory bound to it for code that takes a
``db_factory`` argument.

Shared fakes/factories live in tests/fakes.py (import them, they are not
fixtures).
"""

import pytest


@pytest.fixture(autouse=True)
def _reset_shared_identity_index():
    """Keep the process-wide team identity index out of other tests (#609).

    The index is memoized per process behind a TTL so a run does not rebuild it
    once per event group. Every test gets its own temp database, so without this
    a test could be served an index built from a previous test's team_cache —
    silently matching against the wrong teams.
    """
    from teamarr.consumers.matching.team_matcher import reset_identity_index_cache

    reset_identity_index_cache()
    yield
    reset_identity_index_cache()


@pytest.fixture(autouse=True)
def _reset_provider_rate_limit_waits():
    """A provider's rate-limit deadline is process-wide (#1277).

    A test that answers 429 under a patched sleep leaves a deadline in the
    real future; the next test's first request to that provider would then
    really wait for it.
    """
    from teamarr.providers import base_client

    def _reset():
        for cooldown in list(base_client._cooldowns.values()):
            cooldown._until = 0.0

    _reset()
    yield
    _reset()


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
