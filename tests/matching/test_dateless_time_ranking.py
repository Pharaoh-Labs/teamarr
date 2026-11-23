"""A stream that states a time and no date, against two fixtures of the same teams (#1264).

A provider keeps a stream listed after its game. The name still states the
start ("| 7:00 PM ET") and the team's next fixture is now the nearer day. The
stated time names the game: ranking the day first moved seven real streams to
the next fixture, twice to the reversed one (Sabres at Lightning for
"Lightning at Sabres").

The time stops being evidence only when it cannot tell the two fixtures apart:
both start near it, or neither does because it is written for another zone
("17/11 00:15" is UK time). Then the day decides — and a stream that states
the venue ("A @ B", "A at B") is first held to the meeting played that way
round. A "vs" order is a provider convention and states no venue.

Every case is a real stream name at the date it was last seen, with the two
real start times. Run in both candidate orders — the result must not depend on
which fixture is scored first.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.result import ResultCategory
from teamarr.consumers.matching.team_matcher import (
    DATELESS_TIME_TOLERANCE_SECONDS,
    MatchContext,
)
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

NY = ZoneInfo("America/New_York")


def _team(name: str, short: str, abbr: str, league: str, sport: str) -> Team:
    return Team(
        id=f"{abbr.lower()}-{league}",
        provider="espn",
        name=name,
        short_name=short,
        abbreviation=abbr,
        league=league,
        sport=sport,
    )


def _event(eid: str, away: Team, home: Team, start: str, league: str | None = None) -> Event:
    return Event(
        id=eid,
        provider="espn",
        name=f"{away.name} at {home.name}",
        short_name=f"{away.abbreviation} @ {home.abbreviation}",
        start_time=datetime.fromisoformat(start).replace(tzinfo=NY),
        home_team=home,
        away_team=away,
        status=EventStatus(state="scheduled"),
        league=league or home.league,
        sport=home.sport,
    )


def _nhl(name, short, abbr):
    return _team(name, short, abbr, "nhl", "hockey")


def _nba(name, short, abbr):
    return _team(name, short, abbr, "nba", "basketball")


def _ncaah(name, short, abbr):
    return _team(name, short, abbr, "mens-college-hockey", "hockey")


LIGHTNING = _nhl("Tampa Bay Lightning", "Lightning", "TB")
SABRES = _nhl("Buffalo Sabres", "Sabres", "BUF")
FLYERS = _nhl("Philadelphia Flyers", "Flyers", "PHI")
OILERS = _nhl("Edmonton Oilers", "Oilers", "EDM")
KNICKS = _nba("New York Knicks", "Knicks", "NY")
RAPTORS = _nba("Toronto Raptors", "Raptors", "TOR")
MAGIC = _nba("Orlando Magic", "Magic", "ORL")
CELTICS = _nba("Boston Celtics", "Celtics", "BOS")
NOTRE_DAME = _ncaah("Notre Dame Fighting Irish", "Notre Dame", "ND")
OHIO_STATE = _ncaah("Ohio State Buckeyes", "Ohio State", "OSU")
MICHIGAN_STATE = _ncaah("Michigan State Spartans", "Michigan State", "MSU")
MICHIGAN = _ncaah("Michigan Wolverines", "Michigan", "MICH")
PENN_STATE = _ncaah("Penn State Nittany Lions", "Penn State", "PSU")
WISCONSIN = _ncaah("Wisconsin Badgers", "Wisconsin", "WIS")
KANSAS_FB = _team("Kansas Jayhawks", "Kansas", "KU", "college-football", "football")
WVU_FB = _team("West Virginia Mountaineers", "West Virginia", "WVU", "college-football", "football")
KANSAS_BB = _team("Kansas Jayhawks", "Kansas", "KU", "mens-college-basketball", "basketball")
WVU_BB = _team(
    "West Virginia Mountaineers", "West Virginia", "WVU", "mens-college-basketball", "basketball"
)

# (stream name, last-seen date, the game it names, the team's other fixture)
STALE_STREAMS = [
    (
        "Kansas @ West Virginia | 3:30 PM ET",
        date(2026, 11, 15),
        _event("fb-1114", KANSAS_FB, WVU_FB, "2026-11-14T15:30"),
        _event("bb-1118", KANSAS_BB, WVU_BB, "2026-11-18T19:30"),
    ),
    (
        "Tampa Bay Lightning at Buffalo Sabres | 7:00 PM ET",
        date(2026, 11, 20),
        _event("tb-buf-1111", LIGHTNING, SABRES, "2026-11-11T19:00"),
        _event("buf-tb-1122", SABRES, LIGHTNING, "2026-11-22T17:00"),
    ),
    (
        "Philadelphia Flyers at Edmonton Oilers | 9:00 PM ET",
        date(2026, 11, 20),
        _event("phi-edm-1111", FLYERS, OILERS, "2026-11-11T21:00"),
        _event("edm-phi-1115", OILERS, FLYERS, "2026-11-15T19:30"),
    ),
    (
        "NBA 06: Knicks vs. Raptors (11.15 6:00 PM ET)",
        date(2026, 11, 16),
        _event("ny-tor-1115", KNICKS, RAPTORS, "2026-11-15T18:00"),
        _event("ny-tor-1117", KNICKS, RAPTORS, "2026-11-17T19:30"),
    ),
    (
        "BIG TEN + 004: Ice Hockey (M): Notre Dame at Ohio State (11.20 06:20 PM ET)",
        date(2026, 11, 21),
        _event("nd-osu-1120", NOTRE_DAME, OHIO_STATE, "2026-11-20T18:30"),
        _event("nd-osu-1121", NOTRE_DAME, OHIO_STATE, "2026-11-21T17:00"),
    ),
    (
        "BIG TEN + 009: Ice Hockey (M): Michigan State at Michigan (11.20 06:50 PM ET)",
        date(2026, 11, 21),
        _event("msu-mich-1120", MICHIGAN_STATE, MICHIGAN, "2026-11-20T19:00"),
        _event("mich-msu-1121", MICHIGAN, MICHIGAN_STATE, "2026-11-21T18:00"),
    ),
    (
        "BIG TEN + 010: Ice Hockey (M): Penn State at Wisconsin (11.20 07:50 PM ET)",
        date(2026, 11, 21),
        _event("psu-wis-1120", PENN_STATE, WISCONSIN, "2026-11-20T20:00"),
        _event("psu-wis-1121", PENN_STATE, WISCONSIN, "2026-11-21T19:00"),
    ),
]


def _match(stream_name: str, target: date, candidates: list[Event]):
    classified = classify_stream(stream_name)
    # The premise of every case here: a time, and no date the parser read.
    assert classified.normalized.extracted_time is not None
    assert classified.normalized.extracted_date is None
    ctx = MatchContext(
        stream_name=stream_name,
        stream_id=1,
        group_id=1,
        target_date=target,
        generation=1,
        user_tz=NY,
        classified=classified,
        team1=classified.team1,
        team2=classified.team2,
    )
    out = make_team_matcher()._match_against_candidates(
        ctx, [(event.league, event) for event in candidates]
    )
    assert out.category is ResultCategory.MATCHED
    return out.event.id


@pytest.mark.parametrize("named_first", [True, False], ids=["named-first", "other-first"])
@pytest.mark.parametrize(
    ("stream_name", "target", "named", "other"),
    STALE_STREAMS,
    ids=[case[0] for case in STALE_STREAMS],
)
def test_stream_listed_after_its_game_stays_on_the_game_its_time_names(
    stream_name, target, named, other, named_first
):
    candidates = [named, other] if named_first else [other, named]
    assert _match(stream_name, target, candidates) == named.id


@pytest.mark.parametrize("past_first", [True, False], ids=["past-first", "upcoming-first"])
def test_time_in_another_zone_leaves_the_day_and_the_written_order_to_decide(past_first):
    # 00:15 is UK time for the 19:00 ET tip-off. Read in the user's zone it is
    # 15 h from the earlier meeting and 19 h from this one, so ranking by time
    # put the stream on a finished game played the other way round.
    past = _event("bos-orl-1101", CELTICS, MAGIC, "2026-11-01T15:30")
    upcoming = _event("orl-bos-1116", MAGIC, CELTICS, "2026-11-16T19:00")
    candidates = [past, upcoming] if past_first else [upcoming, past]

    got = _match(
        "GB|SkySports+ 1: Orlando Magic @ Boston Celtics | 17/11 00:15",
        date(2026, 11, 17),
        candidates,
    )

    assert got == upcoming.id


@pytest.mark.parametrize("past_first", [True, False], ids=["past-first", "upcoming-first"])
def test_time_in_another_zone_never_crosses_to_the_reversed_fixture(past_first):
    # Neither start is near the stated time, so the day decides — but the
    # stream's own order names yesterday's game, not tomorrow's return leg.
    past = _event("orl-bos-1116", MAGIC, CELTICS, "2026-11-16T19:00")
    upcoming = _event("bos-orl-1118", CELTICS, MAGIC, "2026-11-18T19:30")
    candidates = [past, upcoming] if past_first else [upcoming, past]

    got = _match(
        "GB|SkySports+ 1: Orlando Magic @ Boston Celtics | 17/11 00:15",
        date(2026, 11, 17),
        candidates,
    )

    assert got == past.id


@pytest.mark.parametrize("past_first", [True, False], ids=["past-first", "upcoming-first"])
def test_vs_order_is_not_a_venue_statement(past_first):
    # 23:40 GMT, twenty minutes before the tip-off, read in the user's zone:
    # near neither meeting. This provider writes the home side first; the
    # league convention we would guess from is away first and would point at
    # the earlier, reversed meeting. "Vs" states no venue, so the day decides.
    past = _event("bos-orl-1101", CELTICS, MAGIC, "2026-11-01T15:30")
    upcoming = _event("orl-bos-1116", MAGIC, CELTICS, "2026-11-16T19:00")
    candidates = [past, upcoming] if past_first else [upcoming, past]

    got = _match(
        "Next: Boston Celtics Vs Orlando Magic : English: NBA: 16-11-2026: 23:40 (GMT):  :"
        " MENA: AR [PPV EVENTS] 22 [1080p]",
        date(2026, 11, 16),
        candidates,
    )

    assert got == upcoming.id


def test_tolerance_separates_a_pre_show_start_from_the_next_night():
    # The replay's tightest pair: "07:50 PM" is 10 minutes from the game it
    # names and 50 from the next night's. The tolerance has to sit between.
    assert 10 * 60 < DATELESS_TIME_TOLERANCE_SECONDS < 50 * 60
