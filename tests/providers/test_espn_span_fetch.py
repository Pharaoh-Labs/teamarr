"""ESPN ranged scoreboard fetch (#808): one call for D-1..D+1, filed into ESPN's own day buckets."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from teamarr.core import Event, EventStatus, Team
from teamarr.providers.espn.provider import ESPNProvider


def _team(name: str) -> Team:
    return Team(
        id=name,
        provider="espn",
        name=name,
        short_name=name,
        abbreviation=name[:3].upper(),
        league="mlb",
        sport="baseball",
    )


def _event(event_id: str, start: datetime) -> Event:
    return Event(
        id=event_id,
        provider="espn",
        name=event_id,
        short_name=event_id,
        start_time=start,
        home_team=_team("H"),
        away_team=_team("A"),
        status=EventStatus(state="scheduled"),
        league="mlb",
        sport="baseball",
    )


@pytest.fixture
def espn(monkeypatch):
    provider = ESPNProvider(client=object(), league_mapping_source=None)
    monkeypatch.setattr(provider, "_get_sport_league_from_db", lambda league: ("baseball", "mlb"))
    monkeypatch.setattr(
        provider,
        "_get_sport",
        lambda league: {"ufc": "mma", "atp": "tennis"}.get(league, "baseball"),
    )
    monkeypatch.setattr(provider, "_is_mma", lambda league, sport: sport == "mma")
    return provider


def test_span_is_one_ranged_request_filed_by_eastern_day(espn, monkeypatch):
    calls: list[str] = []
    events = [
        _event("fri-night", datetime(2026, 9, 12, 1, 40, tzinfo=UTC)),  # 9:40pm ET on the 11th
        _event("sat", datetime(2026, 9, 12, 20, 0, tzinfo=UTC)),
        _event("outside", datetime(2026, 9, 15, 20, 0, tzinfo=UTC)),  # not a wanted day
    ]

    class Client:
        def get_scoreboard(self, league, date_str=None, sport_league=None):
            calls.append(date_str)
            return {"events": ["payload"]}

    espn._client = Client()
    monkeypatch.setattr(espn, "_parse_scoreboard_payload", lambda data, league: list(events))
    buckets = espn.get_events_span("mlb", date(2026, 9, 11), date(2026, 9, 13))
    assert calls == ["20260911-20260913"]
    assert buckets is not None
    assert sorted(buckets) == [date(2026, 9, 11), date(2026, 9, 12), date(2026, 9, 13)]
    assert [e.id for e in buckets[date(2026, 9, 11)]] == ["fri-night"]  # ESPN files by ET date
    assert [e.id for e in buckets[date(2026, 9, 12)]] == ["sat"]
    assert buckets[date(2026, 9, 13)] == []  # empty day still present, so it caches as empty
    assert not any(e.id == "outside" for day in buckets.values() for e in day)


@pytest.mark.parametrize("league", ["ufc", "atp"])
def test_mma_and_tournament_paths_decline_the_span(espn, league):
    class Client:
        def get_scoreboard(self, *a, **k):
            pytest.fail("must not fetch")

    espn._client = Client()
    assert espn.get_events_span(league, date(2026, 9, 11), date(2026, 9, 13)) is None


def test_failed_request_declines_instead_of_caching_empties(espn):
    class Client:
        def get_scoreboard(self, *a, **k):
            return None

    espn._client = Client()
    assert espn.get_events_span("mlb", date(2026, 9, 11), date(2026, 9, 13)) is None


def test_inverted_span_declines(espn):
    assert espn.get_events_span("mlb", date(2026, 9, 13), date(2026, 9, 11)) is None
