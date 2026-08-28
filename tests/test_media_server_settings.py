"""Multi-server Emby/Jellyfin settings tests (#471).

Covers the v83 scalar->list migration, settings roundtrip, and the
masked-secret merge that keeps untouched credentials across full-replace
list updates.
"""

import json
import sqlite3
from pathlib import Path

from teamarr.api.routes.settings.models import MASKED_SECRET, merge_masked_servers
from teamarr.database.migrations import _run_migrations
from teamarr.database.settings import (
    get_emby_settings,
    get_jellyfin_settings,
    update_emby_settings,
    update_jellyfin_settings,
)
from teamarr.database.settings.types import MediaServerEntry


def _make_v82_db(tmp_path: Path) -> sqlite3.Connection:
    """Minimal v82 settings table with the pre-#471 scalar Emby/JF columns."""
    db_path = tmp_path / "media.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            schema_version INTEGER DEFAULT 82,
            emby_enabled BOOLEAN DEFAULT 0,
            emby_url TEXT, emby_username TEXT, emby_password TEXT, emby_api_key TEXT,
            emby_servers JSON,
            jellyfin_enabled BOOLEAN DEFAULT 0,
            jellyfin_url TEXT, jellyfin_username TEXT, jellyfin_password TEXT,
            jellyfin_api_key TEXT,
            jellyfin_servers JSON
        )
        """
    )
    conn.execute(
        """
        INSERT INTO settings (id, schema_version, emby_enabled, emby_url, emby_api_key,
                              jellyfin_enabled, jellyfin_url, jellyfin_username,
                              jellyfin_password)
        VALUES (1, 82, 1, 'http://emby:8096/', 'abc123', 1, 'http://jf:8096',
                'admin', 'hunter2')
        """
    )
    return conn


class TestV83MediaServerLists:
    def test_scalars_fold_into_server_lists(self, tmp_path):
        conn = _make_v82_db(tmp_path)

        _run_migrations(conn)

        row = conn.execute(
            "SELECT schema_version, emby_servers, jellyfin_servers "
            "FROM settings WHERE id = 1"
        ).fetchone()
        assert row["schema_version"] == 89
        emby = json.loads(row["emby_servers"])
        assert emby == [
            {
                "name": "Emby",
                "url": "http://emby:8096",  # trailing slash stripped
                "username": None,
                "password": None,
                "api_key": "abc123",
            }
        ]
        jf = json.loads(row["jellyfin_servers"])
        assert jf[0]["username"] == "admin"
        assert jf[0]["password"] == "hunter2"

    def test_settings_roundtrip(self, db_conn):
        update_emby_settings(
            db_conn,
            enabled=True,
            servers=[
                {"name": "Den", "url": "http://emby1:8096/", "api_key": "k1"},
                {"name": "Cabin", "url": "http://emby2:8096", "password": "p2",
                 "username": "u2"},
            ],
        )
        settings = get_emby_settings(db_conn)
        assert settings.enabled is True
        assert [s.name for s in settings.servers] == ["Den", "Cabin"]
        assert settings.servers[0].url == "http://emby1:8096"
        assert settings.servers[1].password == "p2"

        update_jellyfin_settings(db_conn, servers=[])
        assert get_jellyfin_settings(db_conn).servers == []


class TestMaskedSecretMerge:
    STORED = [
        MediaServerEntry(name="A", url="http://a:8096", password="real-pass",
                         api_key="real-key"),
        MediaServerEntry(name="B", url="http://b:8096", api_key="b-key"),
    ]

    def test_masked_secrets_resolve_by_url(self):
        merged = merge_masked_servers(
            [
                # reordered: B first — must match by URL, not index
                {"name": "B", "url": "http://b:8096", "password": None,
                 "api_key": MASKED_SECRET},
                {"name": "A", "url": "http://a:8096", "password": MASKED_SECRET,
                 "api_key": MASKED_SECRET},
            ],
            self.STORED,
        )
        assert merged[0]["api_key"] == "b-key"
        assert merged[1]["password"] == "real-pass"
        assert merged[1]["api_key"] == "real-key"

    def test_new_secret_passes_through(self):
        merged = merge_masked_servers(
            [{"name": "A", "url": "http://a:8096", "password": "new-pass",
              "api_key": MASKED_SECRET}],
            self.STORED,
        )
        assert merged[0]["password"] == "new-pass"
        assert merged[0]["api_key"] == "real-key"

    def test_new_row_with_masked_secret_gets_none(self):
        # A masked secret on an unknown URL has nothing to merge from
        merged = merge_masked_servers(
            [{"name": "C", "url": "http://c:8096", "password": MASKED_SECRET,
              "api_key": None}],
            [],
        )
        assert merged[0]["password"] is None


class TestFreshCredentialSave:
    """Route-level regression for #491: the update path must NOT mask
    freshly-entered secrets before the merge sees them."""

    def _wire(self, db_conn, monkeypatch):
        from contextlib import contextmanager

        import teamarr.api.routes.settings.emby as emby_routes

        @contextmanager
        def fake_db():
            yield db_conn

        monkeypatch.setattr(emby_routes, "get_db", fake_db)
        return emby_routes

    def test_fresh_password_and_api_key_store_real_values(self, db_conn, monkeypatch):
        import json

        from teamarr.api.routes.settings.models import EmbySettingsUpdate

        routes = self._wire(db_conn, monkeypatch)
        routes.update_emby_settings(
            EmbySettingsUpdate(
                enabled=True,
                servers=[{
                    "name": "Den", "url": "http://emby:8096",
                    "username": "u", "password": "fresh-pw", "api_key": "fresh-key",
                }],
            )
        )
        raw = db_conn.execute(
            "SELECT emby_servers FROM settings WHERE id = 1"
        ).fetchone()[0]
        stored = json.loads(raw)[0]
        # The bug stored None here: model_dump() ran the masking serializer
        assert stored["password"] == "fresh-pw"
        assert stored["api_key"] == "fresh-key"

    def test_masked_round_trip_still_preserves(self, db_conn, monkeypatch):
        import json

        from teamarr.api.routes.settings.models import (
            MASKED_SECRET,
            EmbySettingsUpdate,
        )

        routes = self._wire(db_conn, monkeypatch)
        routes.update_emby_settings(
            EmbySettingsUpdate(
                servers=[{"name": "Den", "url": "http://emby:8096",
                          "username": "u", "password": "fresh-pw", "api_key": None}],
            )
        )
        # UI round-trip: GET shows masked; user saves without touching it
        routes.update_emby_settings(
            EmbySettingsUpdate(
                servers=[{"name": "Den Renamed", "url": "http://emby:8096",
                          "username": "u", "password": MASKED_SECRET, "api_key": None}],
            )
        )
        stored = json.loads(db_conn.execute(
            "SELECT emby_servers FROM settings WHERE id = 1"
        ).fetchone()[0])[0]
        assert stored["name"] == "Den Renamed"
        assert stored["password"] == "fresh-pw"

    def test_get_masks_but_never_stores_mask(self, db_conn, monkeypatch):
        from teamarr.api.routes.settings.models import EmbySettingsUpdate

        routes = self._wire(db_conn, monkeypatch)
        routes.update_emby_settings(
            EmbySettingsUpdate(
                servers=[{"name": "Den", "url": "http://emby:8096",
                          "username": "u", "password": "fresh-pw", "api_key": None}],
            )
        )
        resp = routes.get_emby_settings()
        dumped = resp.model_dump()
        assert dumped["servers"][0]["password"] == "********"
