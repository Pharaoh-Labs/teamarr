"""Tests for v74 migration: preserve EPG-matching off-state after the global
switch removal (epic 3lp1.1).

The global ``settings.epg_match_enabled`` master switch was removed; EPG program
matching and the Dispatcharr channel-source now activate on the per-group
``event_epg_groups.epg_match_enabled`` / ``settings.epg_channel_source_enabled``
flags ALONE. v74 clears those flags when the (now-vestigial) global switch was
OFF, so a user's effective "off" state survives the upgrade instead of silently
turning matching on.
"""

from __future__ import annotations

import sqlite3

from teamarr.database.connection import _migrate_v74_preserve_epg_match_offstate


def _make_db(global_on: bool, channel_source: int, group_flags: list[int]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            epg_match_enabled BOOLEAN DEFAULT 0,
            epg_channel_source_enabled BOOLEAN DEFAULT 0,
            schema_version INTEGER DEFAULT 73
        )
        """
    )
    conn.execute(
        "INSERT INTO settings (id, epg_match_enabled, epg_channel_source_enabled) "
        "VALUES (1, ?, ?)",
        (int(global_on), channel_source),
    )
    conn.execute(
        """
        CREATE TABLE event_epg_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            epg_match_enabled BOOLEAN DEFAULT 0
        )
        """
    )
    for f in group_flags:
        conn.execute("INSERT INTO event_epg_groups (epg_match_enabled) VALUES (?)", (f,))
    conn.commit()
    return conn


def _group_flags(conn: sqlite3.Connection) -> list[int]:
    rows = conn.execute("SELECT epg_match_enabled FROM event_epg_groups ORDER BY id")
    return [r[0] for r in rows]


def _channel_source(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT epg_channel_source_enabled FROM settings WHERE id = 1").fetchone()
    return row[0]


def test_global_off_clears_dependent_flags():
    # Global switch was OFF → matching was globally inert; preserve that off-state.
    conn = _make_db(global_on=False, channel_source=1, group_flags=[1, 0, 1])
    _migrate_v74_preserve_epg_match_offstate(conn)
    assert _channel_source(conn) == 0
    assert _group_flags(conn) == [0, 0, 0]


def test_global_on_leaves_flags_untouched():
    # Global switch was ON → matching ran before and must continue unchanged.
    conn = _make_db(global_on=True, channel_source=1, group_flags=[1, 0, 1])
    _migrate_v74_preserve_epg_match_offstate(conn)
    assert _channel_source(conn) == 1
    assert _group_flags(conn) == [1, 0, 1]


def test_missing_vestigial_column_is_noop():
    # Partial schema without the vestigial global column → no crash, no changes.
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE settings (id INTEGER PRIMARY KEY CHECK (id = 1), "
        "epg_channel_source_enabled BOOLEAN DEFAULT 1)"
    )
    conn.execute("INSERT INTO settings (id, epg_channel_source_enabled) VALUES (1, 1)")
    conn.commit()
    _migrate_v74_preserve_epg_match_offstate(conn)  # must not raise
    assert _channel_source(conn) == 1
