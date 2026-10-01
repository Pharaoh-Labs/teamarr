"""Packet 8B ownership: schema, core isolation, and rename-in-place adoption."""

import sqlite3

import pytest

from teamarr.database.channel_numbers import _get_all_used_channels, get_all_channels_sorted
from teamarr.database.channels import (
    adopt_plugin_channel,
    create_managed_channel,
    find_any_channel_for_event,
    find_existing_channel,
    get_all_managed_channels,
    get_managed_channel,
    get_managed_channel_by_event,
    get_plugin_channel,
    mark_channel_deleted,
    update_managed_channel,
)
from teamarr.database.connection import get_connection, init_db


def _create(conn, *, plugin_id=None, logical_key=None, adoption_key=None, stream_id=17):
    return create_managed_channel(
        conn,
        None,
        "event-1",
        "espn",
        "teamarr.event-1",
        "Original",
        primary_stream_id=stream_id,
        plugin_id=plugin_id,
        plugin_logical_key=logical_key,
        plugin_adoption_key=adoption_key,
    )


def test_fresh_schema_scopes_event_identity_and_plugin_keys(db_path):
    with get_connection(db_path) as conn:
        core = _create(conn)
        first = _create(conn, plugin_id="planner.one", logical_key="event:1", adoption_key="slot:1")
        second = _create(
            conn, plugin_id="planner.two", logical_key="event:1", adoption_key="slot:1"
        )

        assert get_managed_channel(conn, core).plugin_id is None
        assert get_plugin_channel(conn, "planner.one", "event:1").id == first
        assert get_plugin_channel(conn, "planner.two", "event:1").id == second
        assert get_managed_channel_by_event(conn, "event-1", "espn").id == core
        assert (
            find_existing_channel(conn, "event-1", "espn", stream_id=17, mode="separate").id == core
        )
        assert find_any_channel_for_event(conn, "event-1", "espn").id == core
        assert {row.id for row in get_all_managed_channels(conn, core_only=True)} == {core}
        assert {row.id for row in get_all_managed_channels(conn)} == {core, first, second}

        with pytest.raises(sqlite3.IntegrityError):
            _create(conn, plugin_id="planner.one", logical_key="event:1", adoption_key="slot:2")
        with pytest.raises(sqlite3.IntegrityError):
            _create(conn)


def test_deleted_plugin_key_can_be_reused_but_core_cannot_claim_it(db_path):
    with get_connection(db_path) as conn:
        owned = _create(conn, plugin_id="planner.one", logical_key="event:1", adoption_key="slot:1")
        assert mark_channel_deleted(conn, owned)
        assert get_plugin_channel(conn, "planner.one", "event:1") is None
        assert _create(conn, plugin_id="planner.one", logical_key="event:1", adoption_key="slot:1")
        with pytest.raises(ValueError, match="core channels"):
            _create(conn, logical_key="event:2")
        with pytest.raises(ValueError, match="plugin channels require"):
            _create(conn, plugin_id="planner.one")


def test_adoption_updates_same_row_and_dispatcharr_channel_first(db_path):
    with get_connection(db_path) as conn:
        owned = _create(
            conn, plugin_id="planner.one", logical_key="provisional", adoption_key="slot:1"
        )
        conn.execute(
            """UPDATE managed_channels SET dispatcharr_channel_id = 92,
               channel_number = '500' WHERE id = ?""",
            (owned,),
        )
        conn.execute(
            """INSERT INTO managed_channel_streams
               (managed_channel_id, dispatcharr_stream_id) VALUES (?, ?)""",
            (owned, 37),
        )
        seen = []

        def rename(channel, name, tvg_id):
            seen.append((channel.id, channel.plugin_logical_key, name, tvg_id))
            assert get_plugin_channel(conn, "planner.one", "canonical") is None
            return True

        adopted = adopt_plugin_channel(
            conn,
            "planner.one",
            "canonical",
            "slot:1",
            "Canonical Name",
            "canonical.xmltv",
            rename_dispatcharr=rename,
            plan_generation=3,
        )
        assert adopted.id == owned
        assert adopted.channel_number == "500"
        assert adopted.dispatcharr_channel_id == 92
        assert adopted.channel_name == "Canonical Name"
        assert adopted.plugin_plan_generation == 3
        assert get_plugin_channel(conn, "planner.one", "provisional") is None
        assert seen == [(owned, "provisional", "Canonical Name", "canonical.xmltv")]
        assert (
            conn.execute(
                """SELECT dispatcharr_stream_id FROM managed_channel_streams
                   WHERE managed_channel_id = ?""",
                (owned,),
            ).fetchone()[0]
            == 37
        )


def test_adoption_rejects_ambiguity_collision_and_failed_remote_write(db_path):
    with get_connection(db_path) as conn:
        first = _create(conn, plugin_id="planner.one", logical_key="old:a", adoption_key="slot:1")
        second = _create(
            conn, plugin_id="planner.one", logical_key="old:b", adoption_key="slot:1", stream_id=18
        )
        calls = []
        with pytest.raises(ValueError, match="ambiguous"):
            adopt_plugin_channel(
                conn,
                "planner.one",
                "new",
                "slot:1",
                "Name",
                "new.xmltv",
                rename_dispatcharr=lambda *_: calls.append(1) or True,
            )
        assert calls == []
        assert get_managed_channel(conn, first).plugin_logical_key == "old:a"
        assert get_managed_channel(conn, second).plugin_logical_key == "old:b"

        assert mark_channel_deleted(conn, second)
        third = _create(
            conn, plugin_id="planner.one", logical_key="new", adoption_key="slot:2", stream_id=19
        )
        with pytest.raises(ValueError, match="already belongs"):
            adopt_plugin_channel(conn, "planner.one", "new", "slot:1", "Name", "new.xmltv")
        assert get_managed_channel(conn, third).plugin_logical_key == "new"
        conn.execute(
            "UPDATE managed_channels SET dispatcharr_channel_id = 92 WHERE id = ?", (first,)
        )
        with pytest.raises(RuntimeError, match="Dispatcharr rename failed"):
            adopt_plugin_channel(
                conn,
                "planner.one",
                "canonical",
                "slot:1",
                "Name",
                "new.xmltv",
                rename_dispatcharr=lambda *_: False,
            )
        assert get_managed_channel(conn, first).plugin_logical_key == "old:a"
        assert (
            adopt_plugin_channel(conn, "another.planner", "new", "slot:1", "Name", "new.xmltv")
            is None
        )
        with pytest.raises(ValueError, match="ownership"):
            update_managed_channel(conn, first, {"plugin_id": "another.planner"})


def test_upgrade_rebuilds_old_event_index_without_losing_core_channels(db_path):
    with get_connection(db_path) as conn:
        core = _create(conn)
        conn.execute("UPDATE settings SET schema_version = 96")
        conn.execute("DROP INDEX idx_mc_unique_event_v2")
        conn.execute("""CREATE UNIQUE INDEX idx_mc_unique_event
                     ON managed_channels(event_epg_group_id, event_id, event_provider,
                                         COALESCE(exception_keyword, ''), primary_stream_id)
                     WHERE deleted_at IS NULL""")
        conn.execute("""CREATE UNIQUE INDEX idx_mc_unique_event_v2
                     ON managed_channels(event_id, event_provider, COALESCE(exception_keyword, ''),
                                         COALESCE(feed_team_id, ''), primary_stream_id)
                     WHERE deleted_at IS NULL""")
    init_db(db_path)
    with get_connection(db_path) as conn:
        definition = conn.execute(
            "SELECT sql FROM sqlite_master WHERE name = 'idx_mc_unique_event_v2'"
        ).fetchone()[0]
        assert "plugin_id IS NULL" in definition
        assert (
            conn.execute(
                "SELECT 1 FROM sqlite_master WHERE name = 'idx_mc_unique_event'"
            ).fetchone()
            is None
        )
        assert get_managed_channel(conn, core).plugin_id is None
        assert _create(conn, plugin_id="planner.one", logical_key="event:1", adoption_key="slot:1")
        assert conn.execute("SELECT schema_version FROM settings").fetchone()[0] == 97


def test_plugin_ownership_remains_visible_to_numbering_and_api(db_path, monkeypatch):
    import teamarr.api.routes.channels as channels_route

    with get_connection(db_path) as conn:
        owned = _create(conn, plugin_id="planner.one", logical_key="event:1", adoption_key="slot:1")
        conn.execute(
            """UPDATE managed_channels SET channel_number = '501',
               plugin_plan_generation = 3 WHERE id = ?""",
            (owned,),
        )
        assert 501 in _get_all_used_channels(conn)
        assert owned in {channel["id"] for channel in get_all_channels_sorted(conn)}

    monkeypatch.setattr(channels_route, "get_db", lambda: get_connection(db_path))
    response = channels_route.get_managed_channel(owned)
    assert response.plugin_id == "planner.one"
    assert response.plugin_logical_key == "event:1"
    assert response.plugin_adoption_key == "slot:1"
    assert response.plugin_plan_generation == 3
