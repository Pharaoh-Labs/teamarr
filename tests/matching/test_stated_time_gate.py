"""A stream that states its start time cannot match a game most of a day away (#956).

The date check allows one day of slack, because a date alone cannot say which
side of midnight a game falls on. With a time AND a known timezone the stream
says exactly when it starts. On a week of production matches, 95 pairs sat 17
or more hours from the stream's own stated start, all of them wrong: the
previous night's game of a series, a leftover listing for a game that was not
played, or the same two schools in another sport the next afternoon.

Without a known timezone the stated time is not evidence — one provider
stamps every stream 03:00 — so those streams keep the day-level check.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.result import FailedReason
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

TODAY = datetime.now(UTC).date()
LONDON = ZoneInfo("Europe/London")


def _team(name, short, abbr):
    return Team(
        id=abbr.lower(), provider="espn", name=name, short_name=short,
        abbreviation=abbr, league="mlb", sport="baseball",
    )


RAYS = _team("Tampa Bay Rays", "Rays", "TB")
PHILLIES = _team("Philadelphia Phillies", "Phillies", "PHI")


def _game(eid, start):
    return Event(
        id=eid, provider="espn", name="Tampa Bay Rays at Philadelphia Phillies",
        short_name="TB @ PHI", start_time=start, home_team=PHILLIES, away_team=RAYS,
        status=EventStatus(state="scheduled"), league="mlb", sport="baseball",
    )


def _match(stream_name, events, stream_tz):
    cache = MagicMock()
    cache.get.return_value = None
    cache.is_failed_cached.return_value = None
    service = MagicMock()
    service.get_team_schedule.return_value = []
    matcher = make_team_matcher(service=service, cache=cache, include_leagues={"mlb"})
    return matcher.match_multi_league(
        classified=classify_stream(stream_name),
        enabled_leagues=["mlb"],
        target_date=TODAY,
        group_id=1,
        stream_id=1,
        generation=1,
        user_tz=ZoneInfo("UTC"),
        prefetched_events={"mlb": events},
        stream_tz=stream_tz,
    )


def _stamp(when):
    stop = when + timedelta(hours=7)
    return f"MLB 06 : Rays x Phillies start:{when:%Y-%m-%d %H:%M:%S} stop:{stop:%Y-%m-%d %H:%M:%S}"


NOON = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC).replace(hour=18)
TONIGHT = _game("tonight", NOON)
LAST_NIGHT = _game("last-night", NOON - timedelta(hours=20))


def test_stream_matches_the_game_at_its_stated_time():
    result = _match(_stamp(NOON.astimezone(LONDON)), [LAST_NIGHT, TONIGHT], LONDON)
    assert result.event is not None and result.event.id == "tonight"


def test_yesterdays_leg_alone_is_refused():
    """The production case: only the previous night's game is left to match."""
    result = _match(_stamp(NOON.astimezone(LONDON)), [LAST_NIGHT], LONDON)
    assert getattr(result, "event", None) is None
    assert result.failed_reason is FailedReason.DATE_MISMATCH


def test_a_few_hours_out_still_matches():
    """Rain delays and rescheduled first pitches move a game by hours, not a day."""
    shifted = _game("delayed", NOON + timedelta(hours=5))
    result = _match(_stamp(NOON.astimezone(LONDON)), [shifted], LONDON)
    assert result.event is not None and result.event.id == "delayed"


def test_unknown_timezone_keeps_the_day_level_check():
    """No stream marker and no source timezone: the stated time is not evidence."""
    result = _match(_stamp(NOON.astimezone(LONDON)), [LAST_NIGHT], None)
    assert result.event is not None and result.event.id == "last-night"


def test_a_stream_without_a_time_is_unaffected():
    result = _match("MLB 06 : Rays x Phillies", [LAST_NIGHT], LONDON)
    assert result.event is not None and result.event.id == "last-night"
