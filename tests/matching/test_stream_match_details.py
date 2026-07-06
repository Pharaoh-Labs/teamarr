"""Tests for get_stream_match_details — cache-derived 'how it matched' detail.

Reads stream_match_cache to explain a stream's match (matched event, method,
user correction). Used by the Managed Channels method popover.
"""

import json

from teamarr.database.channels.streams import get_stream_match_details


def _insert(db_conn, group_id, stream_id, *, event_id="e1", league="nhl",
            event_name="Hurricanes at Golden Knights", method="fuzzy",
            user_corrected=0, corrected_at=None, updated_at="2026-06-16 00:00:00",
            fingerprint=None):
    data = json.dumps({"name": event_name}) if event_name is not None else None
    db_conn.execute(
        """INSERT INTO stream_match_cache
           (fingerprint, group_id, stream_id, stream_name, event_id, league,
            cached_event_data, match_method, user_corrected, corrected_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (fingerprint or f"fp-{group_id}-{stream_id}-{updated_at}", group_id, stream_id,
         "ESPN", event_id, league, data, method, user_corrected, corrected_at, updated_at),
    )
    db_conn.commit()


def test_returns_match_detail_for_pair(db_conn):
    _insert(db_conn, 1, 100, event_name="Hurricanes at Golden Knights", method="alias",
            user_corrected=1, corrected_at="2026-06-15 12:00:00")

    out = get_stream_match_details(db_conn, [(1, 100)])

    assert (1, 100) in out
    d = out[(1, 100)]
    assert d["event_name"] == "Hurricanes at Golden Knights"
    assert d["league"] == "nhl"
    assert d["match_method"] == "alias"
    assert d["user_corrected"] is True
    assert d["corrected_at"] == "2026-06-15 12:00:00"


def test_failed_match_is_excluded(db_conn):
    _insert(db_conn, 1, 100, event_id="__FAILED__", event_name=None, method="no_match")
    assert get_stream_match_details(db_conn, [(1, 100)]) == {}


def test_unrequested_pairs_excluded(db_conn):
    _insert(db_conn, 1, 100)
    _insert(db_conn, 2, 200)
    out = get_stream_match_details(db_conn, [(1, 100)])
    assert set(out.keys()) == {(1, 100)}


def test_most_recent_row_wins_per_pair(db_conn):
    _insert(db_conn, 1, 100, event_name="Old Event", method="fuzzy",
            updated_at="2026-06-10 00:00:00")
    _insert(db_conn, 1, 100, event_name="New Event", method="alias",
            updated_at="2026-06-16 00:00:00")

    d = get_stream_match_details(db_conn, [(1, 100)])[(1, 100)]
    assert d["event_name"] == "New Event"
    assert d["match_method"] == "alias"


def test_empty_pairs_returns_empty(db_conn):
    assert get_stream_match_details(db_conn, []) == {}


def _insert_event_with_teams(db_conn, group_id, stream_id, *, stream_name, league,
                             home_id, home_name, away_id, away_name, method="alias"):
    data = json.dumps({
        "name": f"{away_name} at {home_name}",
        "home_team": {"id": home_id, "name": home_name},
        "away_team": {"id": away_id, "name": away_name},
    })
    db_conn.execute(
        """INSERT INTO stream_match_cache
           (fingerprint, group_id, stream_id, stream_name, event_id, league,
            cached_event_data, match_method, user_corrected, corrected_at, updated_at)
           VALUES (?, ?, ?, ?, 'e1', ?, ?, ?, 0, NULL, '2026-06-16 00:00:00')""",
        (f"fp-{group_id}-{stream_id}", group_id, stream_id, stream_name, league, data, method),
    )
    db_conn.commit()


def _insert_alias(db_conn, alias, league, team_id, team_name, provider="espn"):
    db_conn.execute(
        "INSERT INTO team_aliases (alias, league, provider, team_id, team_name) "
        "VALUES (?, ?, ?, ?, ?)",
        (alias, league, provider, team_id, team_name),
    )
    db_conn.commit()


def test_alias_mapping_reconstructed_for_alias_match(db_conn):
    _insert_event_with_teams(
        db_conn, 1, 100, stream_name="Spurs vs Lakers HD", league="nba",
        home_id="13", home_name="Los Angeles Lakers",
        away_id="24", away_name="San Antonio Spurs",
    )
    _insert_alias(db_conn, "spurs", "nba", "24", "San Antonio Spurs")
    _insert_alias(db_conn, "celtics", "nba", "2", "Boston Celtics")  # not in this event/name

    d = get_stream_match_details(db_conn, [(1, 100)])[(1, 100)]
    assert d["aliases"] == [{"alias": "spurs", "team": "San Antonio Spurs"}]


def test_non_alias_match_has_no_aliases(db_conn):
    _insert_event_with_teams(
        db_conn, 1, 100, stream_name="Spurs vs Lakers HD", league="nba",
        home_id="13", home_name="Los Angeles Lakers",
        away_id="24", away_name="San Antonio Spurs", method="fuzzy",
    )
    _insert_alias(db_conn, "spurs", "nba", "24", "San Antonio Spurs")

    d = get_stream_match_details(db_conn, [(1, 100)])[(1, 100)]
    assert d["aliases"] == []


def _team(tid, name, short, abbr):
    return {"id": tid, "name": name, "short_name": short, "abbreviation": abbr}


def _insert_event_full_teams(db_conn, stream_name, method, *, home, away):
    """home/away are dicts with id/name/short_name/abbreviation."""
    data = json.dumps({
        "name": f"{away['name']} at {home['name']}",
        "home_team": home,
        "away_team": away,
    })
    db_conn.execute(
        """INSERT INTO stream_match_cache
           (fingerprint, group_id, stream_id, stream_name, event_id, league,
            cached_event_data, match_method, updated_at)
           VALUES ('fp', 1, 100, ?, 'e1', 'mlb', ?, ?, '2026-06-16 00:00:00')""",
        (stream_name, data, method),
    )
    db_conn.commit()


def test_pattern_match_reconstructs_team_token(db_conn):
    _insert_event_full_teams(
        db_conn, "Phillies vs Athletics 1080p", "pattern",
        home=_team("22", "Philadelphia Phillies", "Phillies", "PHI"),
        away=_team("11", "Athletics", "Athletics", "ATH"),
    )
    d = get_stream_match_details(db_conn, [(1, 100)])[(1, 100)]
    # Short name "Phillies" appears; full name doesn't, so token is the short name.
    assert {"token": "Phillies", "team": "Philadelphia Phillies"} in d["patterns"]
    assert {"token": "Athletics", "team": "Athletics"} in d["patterns"]


def test_pattern_abbreviation_matches_on_word_boundary(db_conn):
    _insert_event_full_teams(
        db_conn, "PHI feed", "pattern",
        home=_team("22", "Philadelphia Phillies", "Phils", "PHI"),
        away=_team("11", "New York Mets", "Mets", "NYM"),
    )
    d = get_stream_match_details(db_conn, [(1, 100)])[(1, 100)]
    assert d["patterns"] == [{"token": "PHI", "team": "Philadelphia Phillies"}]


def test_non_pattern_match_has_no_patterns(db_conn):
    _insert_event_full_teams(
        db_conn, "Phillies vs Athletics", "fuzzy",
        home=_team("22", "Philadelphia Phillies", "Phillies", "PHI"),
        away=_team("11", "Athletics", "Athletics", "ATH"),
    )
    d = get_stream_match_details(db_conn, [(1, 100)])[(1, 100)]
    assert d["patterns"] == []
