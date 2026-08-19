"""Tests for the Squiggle AFL provider (iua3.5 coverage gap — was zero tests).

Pins the Squiggle API contract the provider normalizes:
- game["complete"]: 0 → scheduled, 1-99 → live (value is completion %), 100 → final
- game["unixtime"]: UTC unix timestamp, authoritative for scheduling/date filters
- game["is_final"]: truthy → postseason
- scores only surface once a game is underway (complete > 0)
"""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from teamarr.core import SEASON_POSTSEASON, SEASON_REGULAR
from teamarr.providers.squiggle.provider import SquiggleProvider

TEAMS = [
    {"id": 1, "name": "Richmond", "abbrev": "RIC", "logo": "/logos/ric.png"},
    {"id": 2, "name": "Geelong", "abbrev": "GEE", "logo": "/logos/gee.png"},
    {"id": 3, "name": "Carlton"},  # no abbrev/logo — fallback paths
]


def _unix(dt: datetime) -> int:
    return int(dt.timestamp())


def _game(gid=10, hid=1, aid=2, *, when=None, complete=0, is_final=0, **extra):
    when = when or datetime(2026, 7, 10, 9, 30, tzinfo=UTC)
    g = {
        "id": gid,
        "hteamid": hid,
        "ateamid": aid,
        "hteam": "Richmond",
        "ateam": "Geelong",
        "unixtime": _unix(when),
        "complete": complete,
        "is_final": is_final,
        "venue": "MCG",
        "hscore": 88,
        "ascore": 72,
        "year": 2026,
    }
    g.update(extra)
    return g


class _StubClient:
    def __init__(self, games=(), teams=TEAMS, standings=()):
        self._games = list(games)
        self._teams = list(teams)
        self._standings = list(standings)

    def get_games(self, year):
        return self._games

    def get_teams(self):
        return self._teams

    def get_standings(self, year):
        return self._standings

    @staticmethod
    def logo_url(logo_file):
        return f"https://squiggle.com.au{logo_file}"


class _Mapping:
    """LeagueMappingSource stand-in: supports only 'afl' for squiggle."""

    def supports_league(self, league, provider):
        return league == "afl" and provider == "squiggle"

    def get_leagues_for_provider(self, provider):
        return [SimpleNamespace(league_code="afl")]


_MAPPING = _Mapping()


def _provider(games=(), teams=TEAMS, standings=(), mapping=_MAPPING):
    return SquiggleProvider(
        client=_StubClient(games, teams, standings),
        league_mapping_source=mapping,
    )


# ---------------------------------------------------------------------------
# Status mapping (complete percentage → EventStatus)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "complete,state,detail",
    [
        (0, "scheduled", None),
        (None, "scheduled", None),  # API sometimes omits the field
        (1, "live", "1% complete"),
        (55, "live", "55% complete"),
        (100, "final", "Full Time"),
    ],
)
def test_parse_status(complete, state, detail):
    status = SquiggleProvider._parse_status({"complete": complete})
    assert status.state == state
    if detail:
        assert status.detail == detail


# ---------------------------------------------------------------------------
# Team parsing
# ---------------------------------------------------------------------------


def test_parse_team_full():
    team = _provider()._parse_team(TEAMS[0], "afl")
    assert team.id == "1"
    assert team.provider == "squiggle"
    assert team.name == "Richmond"
    assert team.short_name == "Richmond"  # Squiggle has no separate short name
    assert team.abbreviation == "RIC"
    assert team.sport == "australian-football"
    assert team.logo_url == "https://squiggle.com.au/logos/ric.png"


def test_parse_team_fallbacks():
    team = _provider()._parse_team(TEAMS[2], "afl")
    assert team.abbreviation == "CAR"  # first 3 letters uppercased
    assert team.logo_url is None


def test_parse_team_missing_name_returns_none():
    assert _provider()._parse_team({"id": 9}, "afl") is None


# ---------------------------------------------------------------------------
# Game parsing
# ---------------------------------------------------------------------------


def test_parse_game_scheduled_hides_scores():
    p = _provider()
    ev = p._parse_game(_game(complete=0), "afl", p._teams_by_id())
    assert ev.id == "10"
    assert ev.name == "Geelong at Richmond"
    assert ev.short_name == "GEE at RIC"
    assert ev.home_score is None and ev.away_score is None
    assert ev.season_type == SEASON_REGULAR
    assert ev.venue.name == "MCG"
    assert ev.start_time == datetime(2026, 7, 10, 9, 30, tzinfo=UTC)


def test_parse_game_live_surfaces_scores():
    p = _provider()
    ev = p._parse_game(_game(complete=42), "afl", p._teams_by_id())
    assert (ev.home_score, ev.away_score) == (88, 72)
    assert ev.status.state == "live"


def test_parse_game_finals_flag_maps_to_postseason():
    p = _provider()
    ev = p._parse_game(_game(is_final=1), "afl", p._teams_by_id())
    assert ev.season_type == SEASON_POSTSEASON


def test_parse_game_unknown_team_id_builds_fallback_team():
    p = _provider()
    ev = p._parse_game(_game(hid=99, hteam="Fitzroy"), "afl", p._teams_by_id())
    assert ev.home_team.name == "Fitzroy"
    assert ev.home_team.id == "99"


def test_parse_game_without_unixtime_returns_none():
    p = _provider()
    game = _game()
    game["unixtime"] = None
    assert p._parse_game(game, "afl", p._teams_by_id()) is None


# ---------------------------------------------------------------------------
# get_events: unixtime (UTC) drives the date filter; league gating
# ---------------------------------------------------------------------------


def test_get_events_filters_by_utc_date():
    target = date(2026, 7, 10)
    on_date = _game(gid=1, when=datetime(2026, 7, 10, 23, 0, tzinfo=UTC))
    off_date = _game(gid=2, when=datetime(2026, 7, 11, 1, 0, tzinfo=UTC))
    events = _provider(games=[on_date, off_date]).get_events("afl", target)
    assert [e.id for e in events] == ["1"]


def test_get_events_unsupported_league_returns_empty():
    assert _provider(games=[_game()]).get_events("nfl", date(2026, 7, 10)) == []


def test_no_mapping_source_supports_nothing():
    p = SquiggleProvider(client=_StubClient(), league_mapping_source=None)
    assert p.supports_league("afl") is False
    assert p.get_supported_leagues() == []


def test_get_supported_leagues_from_mapping():
    assert _provider().get_supported_leagues() == ["afl"]


# ---------------------------------------------------------------------------
# get_team_schedule: team filter + look-ahead window + sort
# ---------------------------------------------------------------------------


def test_get_team_schedule_windows_and_sorts():
    now = datetime.now(UTC)
    soon = _game(gid=1, when=now + timedelta(days=2))
    later = _game(gid=2, when=now + timedelta(days=5))
    beyond = _game(gid=3, when=now + timedelta(days=30))  # outside 14-day window
    past = _game(gid=4, when=now - timedelta(days=2))
    other_team = _game(gid=5, hid=3, aid=2, when=now + timedelta(days=3))

    events = _provider(games=[later, beyond, soon, past, other_team]).get_team_schedule(
        "1", "afl", days_ahead=14
    )
    assert [e.id for e in events] == ["1", "2"]  # windowed, sorted by start


def test_get_team_schedule_matches_away_side():
    now = datetime.now(UTC)
    away_game = _game(gid=7, hid=2, aid=1, when=now + timedelta(days=1))
    events = _provider(games=[away_game]).get_team_schedule("1", "afl")
    assert [e.id for e in events] == ["7"]


# ---------------------------------------------------------------------------
# Lookups and stats
# ---------------------------------------------------------------------------


def test_get_team_by_id():
    team = _provider().get_team("2", "afl")
    assert team.name == "Geelong"
    assert _provider().get_team("404", "afl") is None


def test_get_event_by_id():
    p = _provider(games=[_game(gid=77)])
    assert p.get_event("77", "afl").id == "77"
    assert p.get_event("404", "afl") is None


def test_get_league_teams():
    teams = _provider().get_league_teams("afl")
    assert [t.name for t in teams] == ["Richmond", "Geelong", "Carlton"]
    assert _provider().get_league_teams("nfl") == []


def test_get_team_stats_record_and_averages():
    standings = [
        {"id": 1, "wins": 10, "losses": 4, "draws": 0, "played": 14,
         "for": 1400, "against": 1120, "rank": 3},
    ]
    stats = _provider(standings=standings).get_team_stats("1", "afl")
    assert stats.record == "10-4"
    assert stats.rank == 3
    assert stats.ppg == 100.0
    assert stats.papg == 80.0


def test_get_team_stats_includes_draws_in_record():
    standings = [
        {"id": 1, "wins": 9, "losses": 4, "draws": 1, "played": 14,
         "for": 700, "against": 700, "rank": 5},
    ]
    assert _provider(standings=standings).get_team_stats("1", "afl").record == "9-4-1"


def test_get_team_stats_unknown_team_returns_none():
    assert _provider(standings=[]).get_team_stats("1", "afl") is None
