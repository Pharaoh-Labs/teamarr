"""v103 disables pattern-only sources that #1056 left reading everything (#1089)."""

from teamarr.database.migrations.versioned import (
    _migrate_v103_disable_unbound_pattern_sources,
    _run_migrations,
)


def _add_pattern_columns(conn):
    # The columns left schema.sql in #1056; an upgraded install still has them.
    conn.execute("ALTER TABLE event_epg_groups ADD COLUMN m3u_group_name_pattern TEXT")
    conn.execute(
        "ALTER TABLE event_epg_groups ADD COLUMN m3u_group_name_pattern_enabled BOOLEAN DEFAULT 0"
    )


def _source(conn, name, *, group_id, pattern_on, enabled=1, channel_source=0):
    conn.execute(
        "INSERT INTO event_epg_groups (name, leagues, m3u_group_id, m3u_group_name_pattern, "
        "m3u_group_name_pattern_enabled, enabled, is_channel_source) "
        "VALUES (?, '[]', ?, ?, ?, ?, ?)",
        (name, group_id, "^LIVE" if pattern_on else None, int(pattern_on), enabled, channel_source),
    )


def _enabled(conn):
    return {
        row["name"]: bool(row["enabled"])
        for row in conn.execute("SELECT name, enabled FROM event_epg_groups")
    }


def test_only_an_enabled_pattern_only_source_with_no_group_is_disabled(db_conn):
    conn = db_conn
    _add_pattern_columns(conn)
    _source(conn, "unbound", group_id=None, pattern_on=True)
    _source(conn, "already off", group_id=None, pattern_on=True, enabled=0)
    _source(conn, "pinned", group_id=42, pattern_on=True)
    _source(conn, "plain", group_id=43, pattern_on=False)
    _source(conn, "channel source", group_id=None, pattern_on=True, channel_source=1)
    _migrate_v103_disable_unbound_pattern_sources(conn)
    assert _enabled(conn) == {
        "unbound": False,
        "already off": False,
        "pinned": True,
        "plain": True,
        "channel source": True,
    }
    _migrate_v103_disable_unbound_pattern_sources(conn)  # idempotent


def test_a_database_that_never_had_the_pattern_columns_is_untouched(db_conn):
    conn = db_conn
    conn.execute("INSERT INTO event_epg_groups (name, leagues, enabled) VALUES ('plain', '[]', 1)")
    _migrate_v103_disable_unbound_pattern_sources(conn)
    assert _enabled(conn) == {"plain": True}


def test_versioned_upgrade_lands_on_104(db_conn):
    _add_pattern_columns(db_conn)
    _source(db_conn, "unbound", group_id=None, pattern_on=True)
    db_conn.execute("UPDATE settings SET schema_version = 102")
    _run_migrations(db_conn)
    assert db_conn.execute("SELECT schema_version FROM settings").fetchone()[0] == 104
    assert _enabled(db_conn) == {"unbound": False}
