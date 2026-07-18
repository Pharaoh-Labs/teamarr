"""Starter-template tombstones (#487).

Deleting or renaming-away a starter template must not cause the seeder to
recreate it on the next run; the explicit restore endpoint is the only way
back.
"""

from teamarr.api.routes.templates import (
    delete_template as api_delete,
)
from teamarr.api.routes.templates import (
    restore_default_templates as api_restore,
)
from teamarr.database.default_templates import (
    DEFAULT_TEMPLATE_SET,
    get_seed_tombstones,
    record_seed_tombstones,
    seed_default_templates,
    seed_names_affected_by,
)
from teamarr.database.templates import get_all_templates

STARTER = DEFAULT_TEMPLATE_SET[0]["name"]


def _names(conn):
    return {t.name for t in get_all_templates(conn)}


class TestTombstoneSemantics:
    def test_deleted_starter_does_not_reseed(self, db_conn):
        # db fixture seeds the full set via init_db
        assert STARTER in _names(db_conn)
        row = next(t for t in get_all_templates(db_conn) if t.name == STARTER)

        from teamarr.database.templates import delete_template as db_delete

        db_delete(db_conn, row.id)
        record_seed_tombstones(db_conn, seed_names_affected_by(STARTER))

        created = seed_default_templates(db_conn)
        assert STARTER not in _names(db_conn)
        assert created == 0

    def test_renamed_starter_does_not_reseed_old_name(self, db_conn):
        row = next(t for t in get_all_templates(db_conn) if t.name == STARTER)

        from teamarr.database.templates import update_template as db_update

        db_update(db_conn, row.id, name="My Custom Version")
        record_seed_tombstones(db_conn, seed_names_affected_by(STARTER))

        seed_default_templates(db_conn)
        names = _names(db_conn)
        assert "My Custom Version" in names
        assert STARTER not in names  # no fresh seed under the old name

    def test_non_starter_name_records_nothing(self, db_conn):
        assert seed_names_affected_by("My Own Template") == set()

    def test_legacy_and_prior_names_map_to_current(self):
        # Deleting a row still named by the LEGACY seed name must tombstone
        # the mapped curated member (which step 2 would otherwise create)
        affected = seed_names_affected_by("Team")
        assert "Default Team (Starter)" in affected

    def test_seed_without_tombstones_recreates(self, db_conn):
        # Sanity: absence WITHOUT a tombstone still reseeds (fresh-install path)
        row = next(t for t in get_all_templates(db_conn) if t.name == STARTER)

        from teamarr.database.templates import delete_template as db_delete

        db_delete(db_conn, row.id)
        created = seed_default_templates(db_conn)
        assert created == 1
        assert STARTER in _names(db_conn)


class TestApiLayer:
    def test_api_delete_tombstones_and_restore_brings_back(self, db_conn, monkeypatch):
        from contextlib import contextmanager

        import teamarr.api.routes.templates as routes

        @contextmanager
        def fake_db():
            yield db_conn

        monkeypatch.setattr(routes, "get_db", fake_db)

        row = next(t for t in get_all_templates(db_conn) if t.name == STARTER)
        api_delete(row.id)

        assert STARTER in get_seed_tombstones(db_conn)
        assert seed_default_templates(db_conn) == 0  # tombstone holds

        result = api_restore()
        assert result["restored"] >= 1
        assert STARTER in _names(db_conn)
        assert get_seed_tombstones(db_conn) == set()
