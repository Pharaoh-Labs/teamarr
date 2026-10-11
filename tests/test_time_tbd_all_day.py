"""A game with no announced time is an all-day placeholder (#995).

ESPN sends midnight Eastern of the game's date. Only the date is real: the
game is anchored to the start of that day where the user is, runs to the next
midnight, takes no pregame lead-in, and is never compared against a time a
stream states.
"""

from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from teamarr.config import clear_timezone_cache, set_timezone
from teamarr.consumers.lifecycle.timing import ChannelLifecycleManager
from teamarr.consumers.matching.team_matcher import _stated_start_gap_hours
from teamarr.core.types import Event, EventStatus, Team
from teamarr.providers.espn.provider import ESPNProvider
from teamarr.utilities.event_status import (
    event_end_time,
    event_programme_start,
    unannounced_day_start,
)

PACIFIC = ZoneInfo("America/Los_Angeles")


@pytest.fixture(params=["America/Los_Angeles", "America/Detroit", "Europe/London"])
def user_tz(request):
    set_timezone(request.param)
    yield ZoneInfo(request.param)
    clear_timezone_cache()


def _team(id_, name):
    return Team(id=id_, provider="espn", name=name, short_name=name, abbreviation=name[:3],
                league="college-football", sport="football")


def _event(start, time_tbd):
    return Event(
        id="401858490", provider="espn", name="x", short_name="x", start_time=start,
        league="college-football", sport="football", status=EventStatus(state="pre"),
        home_team=_team("130", "Michigan Wolverines"),
        away_team=_team("213", "Penn State Nittany Lions"), time_tbd=time_tbd,
    )


def _scoreboard_event(time_valid):
    return {
        "id": "401858490",
        "name": "Penn State Nittany Lions at Michigan Wolverines",
        "shortName": "PSU @ MICH",
        "date": "2026-10-17T04:00Z",
        "competitions": [{
            "id": "401858490",
            "date": "2026-10-17T04:00Z",
            "timeValid": time_valid,
            "competitors": [
                {"id": "130", "homeAway": "home",
                 "team": {"id": "130", "displayName": "Michigan Wolverines",
                          "abbreviation": "MICH"}},
                {"id": "213", "homeAway": "away",
                 "team": {"id": "213", "displayName": "Penn State Nittany Lions",
                          "abbreviation": "PSU"}},
            ],
            "status": {"type": {"state": "pre", "name": "STATUS_SCHEDULED"}},
        }],
    }


def test_the_game_keeps_its_date_wherever_the_user_is(user_tz):
    """Midnight Eastern read as an instant is Friday evening in Los Angeles."""
    start = unannounced_day_start(datetime(2026, 10, 17, 4, 0, tzinfo=UTC))
    local = start.astimezone(user_tz)
    assert (local.date().isoformat(), local.time()) == ("2026-10-17", time(0, 0))


def test_the_provider_anchors_an_unannounced_game_to_its_day(user_tz):
    provider = ESPNProvider(client=MagicMock())
    event = provider._parse_event(_scoreboard_event(False), "college-football")
    local = event.start_time.astimezone(user_tz)
    assert (local.date().isoformat(), local.time()) == ("2026-10-17", time(0, 0))


def test_an_announced_time_is_left_alone(user_tz):
    provider = ESPNProvider(client=MagicMock())
    event = provider._parse_event(_scoreboard_event(True), "college-football")
    assert event.start_time == datetime(2026, 10, 17, 4, 0, tzinfo=UTC)


def test_the_placeholder_runs_the_whole_day_with_no_lead_in(user_tz):
    event = _event(unannounced_day_start(datetime(2026, 10, 17, 4, 0, tzinfo=UTC)), True)
    assert event_programme_start(event, pregame_minutes=30) == event.start_time
    end = event_end_time(event, 3.5).astimezone(user_tz)
    assert (end.date().isoformat(), end.time()) == ("2026-10-18", time(0, 0))


def test_the_day_ends_at_midnight_when_the_clocks_change():
    """1 Nov 2026 is 25 hours long in Los Angeles; start + 24h would stop at 11 PM."""
    set_timezone("America/Los_Angeles")
    try:
        event = _event(unannounced_day_start(datetime(2026, 11, 1, 4, 0, tzinfo=UTC)), True)
        end = event_end_time(event, 3.5)
        assert end.astimezone(PACIFIC).time() == time(0, 0)
        assert end - event.start_time == timedelta(hours=25)
    finally:
        clear_timezone_cache()


def test_an_announced_game_keeps_its_lead_in_and_duration():
    start = datetime(2026, 10, 17, 19, 30, tzinfo=UTC)
    event = _event(start, False)
    assert event_programme_start(event, pregame_minutes=30) == start - timedelta(minutes=30)
    assert event_end_time(event, 3.5) == start + timedelta(hours=3.5)


def test_the_channel_outlives_the_placeholder_day(user_tz):
    """Deletion is anchored to the end of the day, not midnight plus a game length."""
    event = _event(unannounced_day_start(datetime(2026, 10, 17, 4, 0, tzinfo=UTC)), True)
    end = ChannelLifecycleManager().get_event_end_time(event).astimezone(user_tz)
    assert (end.date().isoformat(), end.time()) == ("2026-10-18", time(0, 0))


def _ctx(stated_time):
    normalized = SimpleNamespace(extracted_date=datetime(2026, 10, 17).date(),
                                 extracted_time=stated_time)
    return SimpleNamespace(classified=SimpleNamespace(normalized=normalized),
                           stream_tz=ZoneInfo("America/New_York"))


def test_a_stated_time_is_not_measured_against_the_placeholder():
    """A 3:30 PM stream is 15.5 h from the placeholder — past the 14 h gate."""
    start = datetime(2026, 10, 17, 4, 0, tzinfo=UTC)
    assert _stated_start_gap_hours(_ctx(time(15, 30)), _event(start, False)) == 15.5
    assert _stated_start_gap_hours(_ctx(time(15, 30)), _event(start, True)) == 0.0
