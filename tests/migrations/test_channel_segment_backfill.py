"""v100 backfills managed_channels.segment from the event_id suffix (#1018)."""

import sqlite3

import pytest

from teamarr.database.migrations.versioned import _migrate_v100_backfill_channel_segment


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(
        "CREATE TABLE managed_channels "
        "(id INTEGER PRIMARY KEY, event_id TEXT, sport TEXT, segment TEXT)"
    )
    yield c
    c.close()


def _segments(conn):
    return {
        (r["sport"], r["event_id"]): r["segment"]
        for r in conn.execute("SELECT sport, event_id, segment FROM managed_channels")
    }


def test_backfills_known_suffix_on_racing_and_mma_only(conn):
    rows = [
        ("racing", "401-race", None),
        ("racing", "401-sprint_qualifying", None),
        ("mma", "402-main_card", None),
        ("mma", "402-early_prelims", None),
        ("racing", "403-qualy", None),
        ("racing", "403-other", None),
        ("racing", "404", None),
        ("racing", "405-race", "fp1"),
        ("football", "406-race", None),
        (None, "407-race", None),
    ]
    conn.executemany(
        "INSERT INTO managed_channels (sport, event_id, segment) VALUES (?, ?, ?)", rows
    )
    _migrate_v100_backfill_channel_segment(conn)
    assert _segments(conn) == {
        ("racing", "401-race"): "race",
        ("racing", "401-sprint_qualifying"): "sprint_qualifying",
        ("mma", "402-main_card"): "main_card",
        ("mma", "402-early_prelims"): "early_prelims",
        ("racing", "403-qualy"): None,
        ("racing", "403-other"): None,
        ("racing", "404"): None,
        ("racing", "405-race"): "fp1",
        ("football", "406-race"): None,
        (None, "407-race"): None,
    }


def test_second_run_changes_nothing(conn):
    conn.execute("INSERT INTO managed_channels (sport, event_id) VALUES ('racing', '1-race')")
    _migrate_v100_backfill_channel_segment(conn)
    first = _segments(conn)
    _migrate_v100_backfill_channel_segment(conn)
    assert _segments(conn) == first == {("racing", "1-race"): "race"}


def test_skips_a_table_without_the_columns(conn):
    conn.execute("DROP TABLE managed_channels")
    conn.execute("CREATE TABLE managed_channels (id INTEGER PRIMARY KEY, event_id TEXT)")
    _migrate_v100_backfill_channel_segment(conn)
