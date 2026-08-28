"""NCAA scoreboards must aggregate ESPN's subdivision-specific slates."""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.team_matcher import MatchContext, TeamMatcher
from teamarr.core import Event, Team
from teamarr.providers.espn.client import COLLEGE_SCOREBOARD_GROUPS, ESPNClient


def _client_with_responses(monkeypatch, responses):
    client = ESPNClient()
    calls = []

    def request(url, params=None):
        calls.append((url, params))
        group = (params or {}).get("groups")
        response = responses.get(group)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(client, "_request", request)
    return client, calls


def test_ncaa_coverage_uses_all_configured_subdivision_groups(monkeypatch):
    responses = {
        "90": {"events": [{"id": "fcs"}], "leagues": [{"name": "NCAA Football"}]},
        "35": {"events": [{"id": "d2"}]},
    }
    client, calls = _client_with_responses(monkeypatch, responses)

    result = client.get_scoreboard("college-football", "20260827", ("football", "college-football"))

    assert [event["id"] for event in result["events"]] == ["fcs", "d2"]
    assert [params["groups"] for _, params in calls] == ["90", "35"]
    assert all(params["dates"] == "20260827" for _, params in calls)
    # Never a `limit` (#625): ESPN returns the full slate without one and caps
    # the response at 25 events for any limit above 500. limit=1000 cut Week 1
    # FBS coverage from 68 games to 17.
    assert all("limit" not in params for _, params in calls)


def test_ncaa_scoreboard_warns_when_a_group_looks_capped(monkeypatch, caplog):
    """Exactly 25 events is ESPN's capped-response shape, never a real slate."""
    client, _ = _client_with_responses(
        monkeypatch,
        {"90": {"events": [{"id": str(i)} for i in range(25)]}, "35": {"events": []}},
    )

    with caplog.at_level("WARNING", logger="teamarr.providers.espn.client"):
        client.get_scoreboard("college-football", "20260905", ("football", "college-football"))

    assert any("may be capping" in r.message for r in caplog.records)


def test_ncaa_scoreboard_deduplicates_events_from_overlapping_groups(monkeypatch):
    client, _ = _client_with_responses(
        monkeypatch,
        {
            "90": {"events": [{"id": "shared"}, {"id": "fcs"}]},
            "35": {"events": [{"id": "shared"}, {"id": "d2"}]},
        },
    )

    result = client.get_scoreboard("college-football", "20260827", ("football", "college-football"))

    assert [event["id"] for event in result["events"]] == ["shared", "fcs", "d2"]


def test_ncaa_scoreboard_keeps_successful_group_when_another_is_empty(monkeypatch):
    client, _ = _client_with_responses(
        monkeypatch,
        {"90": {"events": [{"id": "fcs"}]}, "35": None},
    )

    result = client.get_scoreboard("college-football", "20260827", ("football", "college-football"))

    assert result == {"events": [{"id": "fcs"}]}


def test_ncaa_scoreboard_returns_none_when_every_group_is_empty(monkeypatch):
    client, _ = _client_with_responses(monkeypatch, {"90": None, "35": None})

    result = client.get_scoreboard(
        "college-football", "20260827", ("football", "college-football")
    )

    assert result is None


def test_ordinary_scoreboard_remains_one_ungrouped_request(monkeypatch):
    client, calls = _client_with_responses(monkeypatch, {None: {"events": [{"id": "nfl"}]}})

    result = client.get_scoreboard("nfl", "20260827", ("football", "nfl"))

    assert result == {"events": [{"id": "nfl"}]}
    assert calls[0][1] == {"dates": "20260827"}


@pytest.mark.parametrize("league,groups", COLLEGE_SCOREBOARD_GROUPS.items())
def test_every_configured_ncaa_league_merges_its_complete_group_set(monkeypatch, league, groups):
    client, calls = _client_with_responses(
        monkeypatch,
        {group: {"events": [{"id": group}]} for group in groups},
    )

    result = client.get_scoreboard(league, "20260827", ("test-sport", league))

    assert [event["id"] for event in result["events"]] == list(groups)
    assert [params["groups"] for _, params in calls] == list(groups)


FAILED_BUNDLE_FIXTURES = [
    ("Ohio Dominican", "Morehead State", "Ohio Dominican Panthers", "Morehead State Eagles"),
    ("Mercyhurst", "Youngstown State", "Mercyhurst Lakers", "Youngstown State Penguins"),
    ("Eastern Illinois", "Murray State", "Eastern Illinois Panthers", "Murray State Racers"),
    ("Anderson", "Furman", "Anderson (SC) Trojans", "Furman Paladins"),
    ("Lafayette", "Georgetown", "Lafayette Leopards", "Georgetown Hoyas"),
    ("Houston Christian", "SE Louisiana", "Houston Christian Huskies", "SE Louisiana Lions"),
    ("Chattanooga", "West Georgia", "Chattanooga Mocs", "West Georgia Wolves"),
    ("Concord", "Davidson", "Concord Mountain Lions", "Davidson Wildcats"),
    ("Gardner-Webb", "Austin Peay", "Gardner-Webb Runnin' Bulldogs", "Austin Peay Governors"),
    ("Charleston Southern", "Lindenwood", "Charleston Southern Buccaneers", "Lindenwood Lions"),
    (
        "Mississippi Valley State",
        "Nicholls",
        "Mississippi Valley State Delta Devils",
        "Nicholls Colonels",
    ),
    (
        "Northwestern College",
        "Western Illinois",
        "Northwestern (IA) Red Raiders",
        "Western Illinois Leathernecks",
    ),
    ("UVA - Wise", "Presbyterian", "UVA Wise Cavaliers", "Presbyterian Blue Hose"),
    ("Southern Illinois", "West Florida", "Southern Illinois Salukis", "West Florida Argonauts"),
    ("Central Arkansas", "UT Martin", "Central Arkansas Bears", "UT Martin Skyhawks"),
    ("South Dakota School of Mines", "Drake", "South Dakota Mines Hardrockers", "Drake Bulldogs"),
    (
        "Louisiana Christian",
        "Northwestern State",
        "Louisiana Christian University Wildcats",
        "Northwestern State Demons",
    ),
    (
        "Long Island University",
        "North Dakota",
        "Long Island University Sharks",
        "North Dakota Fighting Hawks",
    ),
]


def _event(event_id, away_name, home_name):
    def team(team_id, name):
        return Team(
            id=team_id,
            provider="espn",
            name=name,
            short_name=name,
            abbreviation="",
            league="college-football",
            sport="football",
        )

    return Event(
        id=event_id,
        provider="espn",
        name=f"{away_name} at {home_name}",
        short_name="",
        start_time=datetime(2026, 8, 27, 23, tzinfo=UTC),
        home_team=team(f"{event_id}-home", home_name),
        away_team=team(f"{event_id}-away", away_name),
        status="scheduled",
        league="college-football",
        sport="football",
    )


@pytest.mark.parametrize(
    ("stream_away", "stream_home", "event_away", "event_home"), FAILED_BUNDLE_FIXTURES
)
def test_failed_bundle_fixture_names_match_the_merged_ncaa_slate(
    stream_away, stream_home, event_away, event_home
):
    stream_name = f"NCAAF: {stream_away} vs. {stream_home} @ Aug 27 7:00PM ET"
    classified = classify_stream(stream_name, "team_vs_team", event_league_sport="football")
    matcher = TeamMatcher(service=object(), cache=object())
    context = MatchContext(
        stream_name=stream_name,
        stream_id=1,
        group_id=1,
        target_date=date(2026, 8, 27),
        generation=1,
        user_tz=ZoneInfo("America/New_York"),
        classified=classified,
        team1=classified.team1,
        team2=classified.team2,
    )

    result = matcher._match_against_events(
        context,
        [_event("fixture", event_away, event_home)],
        "college-football",
    )

    assert result.is_matched
    assert result.event.id == "fixture"
