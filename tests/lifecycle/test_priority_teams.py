"""Tests for Priority Teams in channel ordering (4i1 / GH #144).

A priority team floats its channels to the top of the global channel list,
ahead of all sport/league/time ordering. Identity is resolved from team_cache;
channels are matched by (sport, team_name) against home_team/away_team.
"""

from __future__ import annotations

import sqlite3

import pytest

from teamarr.database.channel_numbers import get_all_channels_sorted
from teamarr.database.priority_teams import (
    add_priority_team,
    delete_priority_team,
    get_priority_team_match_keys,
    get_priority_teams,
    update_priority_team_scope,
)
from tests.helpers import SCHEMA_PATH

SCHEMA = SCHEMA_PATH


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
    # New teams default to floating within their league.
    assert get_priority_team_match_keys(conn) == {("soccer", "liverpool"): "league"}


def test_scope_update_and_validation(conn):
    row = add_priority_team(conn, provider="espn", provider_team_id="364", league="eng.1")
    assert row["scope"] == "league"
    assert update_priority_team_scope(conn, row["id"], "sport")["scope"] == "sport"
    assert update_priority_team_scope(conn, row["id"], "bogus") is None
    assert update_priority_team_scope(conn, 9999, "all") is None
    assert add_priority_team(
        conn, provider="espn", provider_team_id="364", league="eng.1", scope="bogus"
    ) is None
    # Re-adding is idempotent and updates scope.
    row = add_priority_team(conn, provider="espn", provider_team_id="364", league="eng.1",
                            scope="all")
    assert row["scope"] == "all"
    assert get_priority_team_match_keys(conn) == {("soccer", "liverpool"): "all"}


def test_existing_rows_without_scope_column_float_everywhere(conn):
    """Pre-scope installs (column added by reconciliation, DEFAULT 'all') keep
    today's behaviour; a bare test schema without the column reads as 'all'."""
    conn.execute("ALTER TABLE channel_priority_teams RENAME TO cpt_old")
    conn.execute("CREATE TABLE channel_priority_teams (id INTEGER PRIMARY KEY, sport TEXT, "
                 "team_name TEXT)")
    conn.execute("INSERT INTO channel_priority_teams (sport, team_name) VALUES ('soccer', 'X')")
    assert get_priority_team_match_keys(conn) == {("soccer", "x"): "all"}


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


# ---------------------------------------------------------------------------
# Float scope: all / sport / league
# ---------------------------------------------------------------------------


def _lineup(conn):
    """Two sports, two leagues each; Liverpool's (soccer, eng.1) game is the
    latest event in the lowest-priority league of the lowest-priority sport."""
    conn.executescript(
        """
        INSERT INTO channel_sort_priorities (sport, league_code, sort_priority) VALUES
          ('football', NULL, 0), ('football', 'nfl', 0),
          ('soccer', NULL, 1), ('soccer', 'usa.1', 0), ('soccer', 'eng.1', 1);
        """
    )
    _add_channel(conn, ch_id=1, sport="football", league="nfl",
                 home="Lions", away="Bears", date="2026-02-01T12:00:00Z")
    _add_channel(conn, ch_id=2, sport="soccer", league="usa.1",
                 home="LAFC", away="Galaxy", date="2026-02-01T12:00:00Z")
    _add_channel(conn, ch_id=3, sport="soccer", league="eng.1",
                 home="Arsenal", away="Chelsea", date="2026-02-01T12:00:00Z")
    _add_channel(conn, ch_id=4, sport="soccer", league="eng.1",
                 home="Liverpool", away="Everton", date="2026-02-09T12:00:00Z")
    conn.commit()
    assert [c["id"] for c in get_all_channels_sorted(conn)] == [1, 2, 3, 4]


def _order(conn):
    return [c["id"] for c in get_all_channels_sorted(conn)]


def test_scope_league_floats_within_league_only(conn):
    _lineup(conn)
    add_priority_team(conn, provider="espn", provider_team_id="364", league="eng.1",
                      scope="league")
    assert _order(conn) == [1, 2, 4, 3]


def test_scope_sport_floats_above_other_leagues_in_sport(conn):
    _lineup(conn)
    add_priority_team(conn, provider="espn", provider_team_id="364", league="eng.1",
                      scope="sport")
    assert _order(conn) == [1, 4, 2, 3]


def test_scope_all_floats_above_everything(conn):
    _lineup(conn)
    add_priority_team(conn, provider="espn", provider_team_id="364", league="eng.1",
                      scope="all")
    assert _order(conn) == [4, 1, 2, 3]
