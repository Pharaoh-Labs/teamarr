"""Tests for Priority Teams in channel ordering (4i1 / GH #144).

A priority team floats its channels to the top of the global channel list,
ahead of all sport/league/time ordering. Identity is resolved from team_cache;
channels are matched by (sport, team_name) against home_team/away_team.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from teamarr.database.channel_numbers import get_all_channels_sorted
from teamarr.database.priority_teams import (
    add_priority_team,
    delete_priority_team,
    get_priority_team_match_keys,
    get_priority_teams,
)

SCHEMA = Path(__file__).resolve().parents[1] / "teamarr" / "database" / "schema.sql"


@pytest.fixture
def conn() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA.read_text())
    # A cached team for resolution.
    db.execute(
        """
        INSERT INTO team_cache
        (team_name, provider, provider_team_id, league, sport, last_seen)
        VALUES ('Liverpool', 'espn', '364', 'eng.1', 'soccer', '2026-01-01T00:00:00Z')
        """
    )
    db.commit()
    return db


def _add_channel(conn, *, ch_id, sport, league, home, away, date):
    conn.execute(
        """
        INSERT INTO managed_channels
        (id, event_id, event_provider, tvg_id, channel_name, sport, league,
         home_team, away_team, event_date)
        VALUES (?, ?, 'espn', ?, ?, ?, ?, ?, ?, ?)
        """,
        (ch_id, f"ev{ch_id}", f"tvg{ch_id}", f"{home} vs {away}",
         sport, league, home, away, date),
    )


# ---------------------------------------------------------------------------
# CRUD + resolution
# ---------------------------------------------------------------------------


def test_add_resolves_name_and_sport_from_cache(conn):
    team = add_priority_team(conn, provider="espn", provider_team_id="364", league="eng.1")
    assert team is not None
    assert team["team_name"] == "Liverpool"
    assert team["sport"] == "soccer"


def test_add_unknown_team_returns_none(conn):
    assert add_priority_team(conn, provider="espn", provider_team_id="999", league="eng.1") is None


def test_add_is_idempotent(conn):
    add_priority_team(conn, provider="espn", provider_team_id="364", league="eng.1")
    add_priority_team(conn, provider="espn", provider_team_id="364", league="eng.1")
    assert len(get_priority_teams(conn)) == 1


def test_delete_removes_row(conn):
    team = add_priority_team(conn, provider="espn", provider_team_id="364", league="eng.1")
    assert delete_priority_team(conn, team["id"]) is True
    assert get_priority_teams(conn) == []


def test_match_keys_are_sport_scoped_lowercase(conn):
    add_priority_team(conn, provider="espn", provider_team_id="364", league="eng.1")
    assert get_priority_team_match_keys(conn) == {("soccer", "liverpool")}


# ---------------------------------------------------------------------------
# Sort behaviour
# ---------------------------------------------------------------------------


def test_priority_team_floats_to_top(conn):
    # Normal channel is earlier; priority channel is later — without the tier the
    # earlier one would lead. The priority team must override that.
    _add_channel(
        conn, ch_id=1, sport="soccer", league="eng.1",
        home="Arsenal", away="Chelsea", date="2026-02-01T12:00:00Z",
    )
    _add_channel(
        conn, ch_id=2, sport="soccer", league="eng.1",
        home="Liverpool", away="Everton", date="2026-02-09T12:00:00Z",
    )
    conn.commit()

    # Baseline: earlier event leads.
    assert [c["id"] for c in get_all_channels_sorted(conn)] == [1, 2]

    # With Liverpool prioritized, its later channel floats above the earlier one.
    add_priority_team(conn, provider="espn", provider_team_id="364", league="eng.1")
    conn.commit()
    assert [c["id"] for c in get_all_channels_sorted(conn)] == [2, 1]


def test_priority_matches_away_team_too(conn):
    _add_channel(
        conn, ch_id=1, sport="soccer", league="eng.1",
        home="Arsenal", away="Chelsea", date="2026-02-01T12:00:00Z",
    )
    _add_channel(
        conn, ch_id=2, sport="soccer", league="eng.1",
        home="Everton", away="Liverpool", date="2026-02-09T12:00:00Z",
    )
    add_priority_team(conn, provider="espn", provider_team_id="364", league="eng.1")
    conn.commit()
    assert [c["id"] for c in get_all_channels_sorted(conn)][0] == 2


def test_priority_does_not_cross_sports(conn):
    # The fixture's soccer "Liverpool" is prioritized; a same-named football team
    # must NOT float (sport-scoped match).
    _add_channel(
        conn, ch_id=1, sport="football", league="nfl",
        home="Liverpool", away="Bears", date="2026-02-01T12:00:00Z",
    )
    _add_channel(
        conn, ch_id=2, sport="football", league="nfl",
        home="Lions", away="Packers", date="2026-02-02T12:00:00Z",
    )
    add_priority_team(conn, provider="espn", provider_team_id="364", league="eng.1")
    conn.commit()
    # soccer Liverpool prioritized; the football "Liverpool" channel must not float.
    assert [c["id"] for c in get_all_channels_sorted(conn)] == [1, 2]
