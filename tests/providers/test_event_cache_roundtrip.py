"""Event cache serialization round-trip (#363, #365).

The scoreboard cache (SportsDataService → event_to_dict/dict_to_event) must
carry every field the template layer reads — a cache hit that silently drops
editorial copy or the neutral-site flag would make the has_event_note /
has_match_note / is_neutral_site conditions and their vars flicker off for
the whole TTL window.
"""

from datetime import UTC, datetime

from teamarr.core.types import Event, EventStatus, Team, Venue
from teamarr.database.provider_cache import dict_to_event, event_to_dict


def _event(**kw) -> Event:
    team = Team(
        id="1", provider="espn", name="Boston Celtics", short_name="Celtics",
        abbreviation="BOS", league="nba", sport="basketball",
    )
    base = dict(
        id="e1", provider="espn", name="DET @ BOS", short_name="DET @ BOS",
        start_time=datetime(2026, 7, 10, 19, 0, tzinfo=UTC),
        home_team=team, away_team=team, status=EventStatus(state="pre"),
        league="nba", sport="basketball",
        venue=Venue(name="TD Garden", city="Boston", state="MA"),
    )
    base.update(kw)
    return Event(**base)


def test_editorial_fields_survive_cache_roundtrip():
    ev = _event(
        game_recap="Celtics top Pistons for the title",
        game_event_note="NBA Finals - Game 5",
        soccer_match_note="FIFA World Cup, Group C",
        game_preview="Pistons (8-4) vs. Celtics…",
        series_summary="Series tied 1-1",
        home_last_five="4-1",
        away_last_five="2-3",
    )
    back = dict_to_event(event_to_dict(ev))
    assert back.game_recap == ev.game_recap
    assert back.game_event_note == ev.game_event_note
    assert back.soccer_match_note == ev.soccer_match_note
    assert back.game_preview == ev.game_preview
    assert back.series_summary == ev.series_summary
    assert back.home_last_five == ev.home_last_five
    assert back.away_last_five == ev.away_last_five


def test_neutral_site_survives_cache_roundtrip():
    assert dict_to_event(event_to_dict(_event(neutral_site=True))).neutral_site is True
    assert dict_to_event(event_to_dict(_event())).neutral_site is False


def test_pre_upgrade_cache_entries_deserialize():
    """Entries written before these fields existed must still load."""
    data = event_to_dict(_event())
    for key in (
        "neutral_site", "game_recap", "game_event_note", "soccer_match_note",
        "game_preview", "series_summary", "home_last_five", "away_last_five",
    ):
        data.pop(key)
    back = dict_to_event(data)
    assert back.neutral_site is False
    assert back.game_event_note == ""
