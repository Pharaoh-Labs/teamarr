"""Tests for Regional Sports Network (RSN) feed resolution and broadcaster ingestion."""

from datetime import UTC, datetime

from teamarr.consumers.event_group_processor.matching import StreamMatching
from teamarr.core.rsn_catalog import resolve_unambiguous_rsn_team, team_matches_rsn
from teamarr.providers.mlbstats.provider import MLBStatsProvider
from tests.fakes import FakeTeam, make_event


def test_rsn_catalog_unambiguous_1to1_resolution():
    """Unambiguous 1:1 RSNs resolve to their affiliated team abbreviation."""
    assert resolve_unambiguous_rsn_team("US: YES Network HD", league="mlb") == "NYY"
    assert resolve_unambiguous_rsn_team("YES HD", league="mlb") == "NYY"
    assert resolve_unambiguous_rsn_team("NESN+", league="mlb") == "BOS"
    assert resolve_unambiguous_rsn_team("US| NESN HD", league="mlb") == "BOS"
    assert resolve_unambiguous_rsn_team("Marquee Sports Network", league="mlb") == "CHC"
    assert resolve_unambiguous_rsn_team("SNY (SportsNet New York)", league="mlb") == "NYM"
    assert resolve_unambiguous_rsn_team("Spectrum SportsNet LA", league="mlb") == "LAD"
    assert resolve_unambiguous_rsn_team("FanDuel Sports Network Detroit", league="mlb") == "DET"
    assert resolve_unambiguous_rsn_team("Bally Sports Wisconsin", league="mlb") == "MIL"
    assert resolve_unambiguous_rsn_team("Padres.TV HD", league="mlb") == "SD"


def test_rsn_catalog_ambiguous_zero_guessing():
    """Ambiguous multi-team RSNs (like MASN) return None (zero guessing)."""
    assert resolve_unambiguous_rsn_team("US: MASN HD", league="mlb") is None
    assert resolve_unambiguous_rsn_team("MASN 2", league="mlb") is None
    assert resolve_unambiguous_rsn_team("MASN2 HD", league="mlb") is None
    assert resolve_unambiguous_rsn_team("Random Non-RSN Stream", league="mlb") is None


def test_team_matches_rsn_helper():
    """Test team abbreviation and name synonym matching."""
    yankees = FakeTeam(id="147", name="New York Yankees", abbreviation="NYY")
    red_sox = FakeTeam(id="111", name="Boston Red Sox", abbreviation="BOS")

    assert team_matches_rsn(yankees, "NYY") is True
    assert team_matches_rsn(yankees, "BOS") is False
    assert team_matches_rsn(red_sox, "BOS") is True
    assert team_matches_rsn(red_sox, "NYY") is False


def test_mlbstats_provider_broadcast_parsing():
    """MLBStatsProvider extracts broadcasts and broadcast_markets from schedule payload."""
    provider = MLBStatsProvider()
    game_data = {
        "gamePk": 745821,
        "gameDate": "2026-06-15T23:05:00Z",
        "teams": {
            "away": {
                "team": {
                    "id": 111,
                    "name": "Boston Red Sox",
                    "abbreviation": "BOS",
                    "teamName": "Red Sox",
                }
            },
            "home": {
                "team": {
                    "id": 147,
                    "name": "New York Yankees",
                    "abbreviation": "NYY",
                    "teamName": "Yankees",
                }
            },
        },
        "status": {"abstractGameState": "Live", "detailedState": "In Progress"},
        "broadcasts": [
            {"id": 1, "name": "YES", "type": "TV", "homeAway": "home", "isNational": False},
            {"id": 2, "name": "NESN", "type": "TV", "homeAway": "away", "isNational": False},
            {"id": 3, "name": "ESPN", "type": "TV", "isNational": True},
        ],
    }

    event = provider._parse_game(game_data, "mlb")
    assert event is not None
    assert "YES" in event.broadcasts
    assert "NESN" in event.broadcasts
    assert "ESPN" in event.broadcasts
    assert event.broadcast_markets == {
        "YES": "home",
        "NESN": "away",
        "ESPN": "national",
    }


def test_resolve_feed_teams_with_rsn_catalog_home():
    """StreamMatching._resolve_feed_teams maps YES stream to Yankees home feed."""
    matcher = StreamMatching()
    yankees = FakeTeam(id="147", name="New York Yankees", abbreviation="NYY")
    red_sox = FakeTeam(id="111", name="Boston Red Sox", abbreviation="BOS")

    event = make_event(
        id="1001",
        league="mlb",
        sport="baseball",
        start_time=datetime(2026, 6, 15, 23, 5, tzinfo=UTC),
        home_team=yankees,
        away_team=red_sox,
    )

    matched_streams = [
        {
            "stream": {"id": 1, "name": "US: YES Network HD", "tvg_id": "YES.us"},
            "event": event,
            "feed_hint": None,
        }
    ]

    resolved = matcher._resolve_feed_teams(
        matched_streams, detect_team_names=True, separation_enabled=True
    )

    assert len(resolved) == 1
    assert resolved[0]["stream_feed_team"] == yankees
    assert resolved[0]["feed_team"] == yankees


def test_resolve_feed_teams_with_rsn_catalog_away():
    """StreamMatching._resolve_feed_teams maps NESN stream to Red Sox away feed."""
    matcher = StreamMatching()
    yankees = FakeTeam(id="147", name="New York Yankees", abbreviation="NYY")
    red_sox = FakeTeam(id="111", name="Boston Red Sox", abbreviation="BOS")

    event = make_event(
        id="1001",
        league="mlb",
        sport="baseball",
        start_time=datetime(2026, 6, 15, 23, 5, tzinfo=UTC),
        home_team=yankees,
        away_team=red_sox,
    )

    matched_streams = [
        {
            "stream": {"id": 2, "name": "US: NESN FHD", "tvg_id": "NESN.us"},
            "event": event,
            "feed_hint": None,
        }
    ]

    resolved = matcher._resolve_feed_teams(
        matched_streams, detect_team_names=True, separation_enabled=True
    )

    assert len(resolved) == 1
    assert resolved[0]["stream_feed_team"] == red_sox
    assert resolved[0]["feed_team"] == red_sox


def test_resolve_feed_teams_ambiguous_masn_yields_none():
    """StreamMatching._resolve_feed_teams leaves ambiguous MASN as unassigned feed."""
    matcher = StreamMatching()
    orioles = FakeTeam(id="110", name="Baltimore Orioles", abbreviation="BAL")
    nationals = FakeTeam(id="120", name="Washington Nationals", abbreviation="WSH")

    event = make_event(
        id="1002",
        league="mlb",
        sport="baseball",
        start_time=datetime(2026, 6, 15, 23, 5, tzinfo=UTC),
        home_team=orioles,
        away_team=nationals,
    )

    matched_streams = [
        {
            "stream": {"id": 3, "name": "US: MASN HD", "tvg_id": "MASN.us"},
            "event": event,
            "feed_hint": None,
        }
    ]

    resolved = matcher._resolve_feed_teams(
        matched_streams, detect_team_names=False, separation_enabled=True
    )

    assert len(resolved) == 1
    assert resolved[0]["stream_feed_team"] is None
    assert resolved[0]["feed_team"] is None


def test_resolve_feed_teams_unrelated_rsn_yields_none():
    """StreamMatching._resolve_feed_teams does not map YES to a Cubs vs Cardinals game."""
    matcher = StreamMatching()
    cubs = FakeTeam(id="112", name="Chicago Cubs", abbreviation="CHC")
    cardinals = FakeTeam(id="138", name="St. Louis Cardinals", abbreviation="STL")

    event = make_event(
        id="1003",
        league="mlb",
        sport="baseball",
        start_time=datetime(2026, 6, 15, 23, 5, tzinfo=UTC),
        home_team=cardinals,
        away_team=cubs,
    )

    matched_streams = [
        {
            "stream": {"id": 4, "name": "US: YES Network HD", "tvg_id": "YES.us"},
            "event": event,
            "feed_hint": None,
        }
    ]

    resolved = matcher._resolve_feed_teams(
        matched_streams, detect_team_names=True, separation_enabled=True
    )

    assert len(resolved) == 1
    assert resolved[0]["stream_feed_team"] is None
    assert resolved[0]["feed_team"] is None
