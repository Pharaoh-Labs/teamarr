"""{today_tonight} knows how far away the game is (#550).

It used to be a bare 5pm cutoff — "today" or "tonight" — with no idea of the
game's date. A racing weekend creates the race channel alongside Saturday
practice, so all Saturday the pregame filler read "... Race from Iowa Speedway
today at 3:30 PM EDT" for a Sunday race. Same-day output is unchanged; earlier
channels now follow {relative_day}'s ladder.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from teamarr.core.types import Event, EventStatus, Team
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.variables.datetime import (
    extract_today_tonight,
    extract_today_tonight_title,
)

TZ = ZoneInfo("America/New_York")
# A Saturday morning, the moment the race channel appeared in the report.
NOW = datetime(2026, 8, 8, 8, 47, tzinfo=UTC)


def _team(tid: str, name: str) -> Team:
    return Team(
        id=tid,
        provider="nascar",
        name=name,
        short_name=name,
        abbreviation=name[:3].upper(),
        league="nascar-cup",
        sport="racing",
    )


def _event(start: datetime) -> Event:
    return Event(
        id="5620",
        provider="nascar",
        name="Iowa Corn 350",
        short_name="Iowa Corn 350",
        start_time=start,
        league="nascar-cup",
        sport="racing",
        status=EventStatus(state="pre"),
        home_team=_team("h", "Field"),
        away_team=_team("a", "Field"),
    )


@pytest.fixture(autouse=True)
def frozen_clock(monkeypatch):
    frozen = NOW.astimezone(TZ)
    monkeypatch.setattr("teamarr.templates.variables.datetime.now_user", lambda: frozen)
    monkeypatch.setattr(
        "teamarr.templates.variables.datetime.to_user_tz", lambda dt: dt.astimezone(TZ)
    )


def _ctx(gc: GameContext) -> TemplateContext:
    tc = TeamChannelContext(team_id="h", league="nascar-cup", sport="racing", team_name="Field")
    return TemplateContext(game_context=gc, team_config=tc, team_stats=None)


def _render(start: datetime) -> tuple[str, str]:
    gc = GameContext(event=_event(start))
    ctx = _ctx(gc)
    return extract_today_tonight(ctx, gc), extract_today_tonight_title(ctx, gc)


def test_sunday_race_seen_on_saturday_is_tomorrow():
    """The exact report: race Sunday 19:30Z, channel created Saturday 08:47Z."""
    assert _render(datetime(2026, 8, 9, 19, 30, tzinfo=UTC)) == ("tomorrow", "Tomorrow")


def test_same_day_afternoon_is_still_today():
    assert _render(datetime(2026, 8, 8, 19, 30, tzinfo=UTC)) == ("today", "Today")


def test_same_day_evening_is_still_tonight():
    assert _render(datetime(2026, 8, 8, 23, 30, tzinfo=UTC)) == ("tonight", "Tonight")


def test_a_few_days_out_names_the_weekday():
    assert _render(datetime(2026, 8, 11, 19, 30, tzinfo=UTC)) == ("tuesday", "Tuesday")


def test_a_week_out_gives_the_date():
    assert _render(datetime(2026, 8, 20, 19, 30, tzinfo=UTC)) == ("Aug 20", "Aug 20")


def test_last_game_stays_time_of_day():
    """.last games are in the past; the ladder treats them as same-day words."""
    assert _render(NOW - timedelta(days=2)) == ("today", "Today")


def test_no_event_is_empty():
    gc = GameContext(event=None)
    ctx = _ctx(gc)
    assert extract_today_tonight(ctx, gc) == ""
