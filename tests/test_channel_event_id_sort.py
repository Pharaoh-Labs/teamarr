"""Tests for numeric-aware event_id tie-break in global channel sort (Phase 3a, item 14).

``get_all_channels_sorted``'s internal ``sort_key`` currently tie-breaks on
``str(event_id)``, so lexicographic ordering makes "10" sort before "2".
New contract: numeric event_ids compare numerically ("2" before "10"); a
numeric event_id sorts before a non-numeric one; two non-numeric ids fall
back to string comparison. This mirrors the existing db-fixture pattern in
test_priority_teams.py (in-memory sqlite + schema.sql).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from teamarr.database.channel_numbers import get_all_channels_sorted

SCHEMA = Path(__file__).resolve().parents[1] / "teamarr" / "database" / "schema.sql"


@pytest.fixture
def conn() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA.read_text())
    db.commit()
    return db


def _add_channel(conn, *, ch_id, event_id, date="2026-02-01T12:00:00Z"):
    # Same sport/league/date for every row in these tests, so the only thing
    # that can break the tie between channels is the event_id comparison.
    conn.execute(
        """
        INSERT INTO managed_channels
        (id, event_id, event_provider, tvg_id, channel_name, sport, league,
         home_team, away_team, event_date)
        VALUES (?, ?, 'espn', ?, ?, 'soccer', 'eng.1', 'A', 'B', ?)
        """,
        (ch_id, event_id, f"tvg{ch_id}", f"chan{ch_id}", date),
    )


def test_numeric_event_ids_sort_numerically_not_lexicographically(conn):
    # "10" sorts before "2" lexicographically (string compare), but 2 < 10
    # numerically. Everything else about the two channels is identical, so
    # only the event_id tie-break can decide the order.
    _add_channel(conn, ch_id=1, event_id="10")
    _add_channel(conn, ch_id=2, event_id="2")
    conn.commit()
    assert [c["id"] for c in get_all_channels_sorted(conn)] == [2, 1]


def test_numeric_event_id_sorts_before_non_numeric(conn):
    # Documented choice: a purely numeric event_id sorts ahead of a
    # non-numeric one (e.g. a provider-specific slug id), regardless of the
    # non-numeric id's string value.
    #
    # These specific values are chosen so plain string comparison disagrees
    # with the desired outcome: "30x" < "4" lexicographically (since '3' <
    # '4' as characters), so the OLD str(event_id) tie-break would put the
    # non-numeric "30x" first. The new numeric-before-non-numeric rule must
    # override that and put the numeric "4" first regardless.
    assert "30x" < "4"  # sanity: confirms the old string order would disagree
    _add_channel(conn, ch_id=1, event_id="30x")
    _add_channel(conn, ch_id=2, event_id="4")
    conn.commit()
    assert [c["id"] for c in get_all_channels_sorted(conn)] == [2, 1]


def test_two_non_numeric_event_ids_fall_back_to_string_compare(conn):
    _add_channel(conn, ch_id=1, event_id="zeta")
    _add_channel(conn, ch_id=2, event_id="alpha")
    conn.commit()
    assert [c["id"] for c in get_all_channels_sorted(conn)] == [2, 1]
