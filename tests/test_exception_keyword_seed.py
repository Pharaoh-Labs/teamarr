"""Default exception keywords are seeded once, not on every startup (#726).

`schema.sql` used to carry an `INSERT OR IGNORE` seed for the eight default
language keywords, and `conn.executescript` replays it on every `init_db()`.
A user who deleted "Spanish" got it back — and Spanish channels with it — the
next time Teamarr restarted. Seeding now records each label it has offered, so
a delete (or a rename away from the default label) survives restarts.
"""

import sqlite3

import pytest

from teamarr.database.connection import init_db
from teamarr.database.exception_keywords import (
    DEFAULT_EXCEPTION_KEYWORDS,
    create_keyword,
    delete_keyword,
    get_all_keywords,
    seed_default_exception_keywords,
)
from teamarr.database.migrations import _run_migrations

DEFAULT_LABELS = {label for label, _terms, _behavior in DEFAULT_EXCEPTION_KEYWORDS}


def _labels(conn: sqlite3.Connection) -> set[str]:
    return {kw.label for kw in get_all_keywords(conn, include_disabled=True)}


def _open(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "teamarr.db"
    init_db(path)
    return path


class TestFreshInstall:
    def test_defaults_are_seeded(self, db_path):
        conn = _open(db_path)
        assert DEFAULT_LABELS <= _labels(conn)

    def test_seed_is_recorded(self, db_path):
        conn = _open(db_path)
        seeded = {r[0] for r in conn.execute("SELECT label FROM seeded_default_exception_keywords")}
        assert seeded == DEFAULT_LABELS

    def test_reinit_does_not_duplicate(self, db_path):
        init_db(db_path)
        conn = _open(db_path)
        rows = conn.execute(
            "SELECT COUNT(*) FROM consolidation_exception_keywords WHERE label = 'Spanish'"
        ).fetchone()[0]
        assert rows == 1


class TestDeletionSurvivesRestart:
    def test_deleted_default_stays_deleted(self, db_path):
        conn = _open(db_path)
        spanish = next(kw for kw in get_all_keywords(conn) if kw.label == "Spanish")
        assert delete_keyword(conn, spanish.id)
        conn.close()

        init_db(db_path)  # the restart that used to resurrect it

        conn = _open(db_path)
        assert "Spanish" not in _labels(conn)
        assert "French" in _labels(conn)  # untouched defaults still there

    def test_renamed_default_is_not_reseeded(self, db_path):
        conn = _open(db_path)
        spanish = next(kw for kw in get_all_keywords(conn) if kw.label == "Spanish")
        conn.execute(
            "UPDATE consolidation_exception_keywords SET label = 'Castellano' WHERE id = ?",
            (spanish.id,),
        )
        conn.commit()
        conn.close()

        init_db(db_path)

        conn = _open(db_path)
        labels = _labels(conn)
        assert "Castellano" in labels
        assert "Spanish" not in labels

    def test_all_defaults_deleted_stay_deleted(self, db_path):
        conn = _open(db_path)
        for kw in get_all_keywords(conn, include_disabled=True):
            delete_keyword(conn, kw.id)
        conn.close()

        init_db(db_path)

        conn = _open(db_path)
        assert _labels(conn) == set()

    def test_user_keywords_are_untouched(self, db_path):
        conn = _open(db_path)
        create_keyword(conn, "Manningcast", "Manningcast, Peyton and Eli", "separate")
        conn.close()

        init_db(db_path)

        conn = _open(db_path)
        assert "Manningcast" in _labels(conn)


class TestNewDefaultsStillReachExistingInstalls:
    def test_label_absent_from_marker_is_seeded(self, db_path):
        """A default added in a later release is offered once to old installs."""
        conn = _open(db_path)
        conn.execute("DELETE FROM seeded_default_exception_keywords WHERE label = 'Korean'")
        conn.execute("DELETE FROM consolidation_exception_keywords WHERE label = 'Korean'")
        conn.commit()

        assert seed_default_exception_keywords(conn) == 1
        assert "Korean" in _labels(conn)

        # ...and only once.
        assert seed_default_exception_keywords(conn) == 0


class TestV93Migration:
    def test_existing_install_is_backfilled(self, tmp_path):
        """Upgrading must not re-add defaults the user already deleted."""
        path = tmp_path / "upgrade.db"
        init_db(path)

        conn = _open(path)
        # Simulate a pre-v93 install: no marker rows, user deleted Spanish.
        conn.execute("DELETE FROM seeded_default_exception_keywords")
        conn.execute("DELETE FROM consolidation_exception_keywords WHERE label = 'Spanish'")
        conn.execute("UPDATE settings SET schema_version = 92 WHERE id = 1")
        conn.commit()

        _run_migrations(conn)

        seeded = {r[0] for r in conn.execute("SELECT label FROM seeded_default_exception_keywords")}
        assert seeded == DEFAULT_LABELS
        assert seed_default_exception_keywords(conn) == 0
        assert "Spanish" not in _labels(conn)
