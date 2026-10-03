"""Equal scores go to the event the stream names outright (#799).

token_set_ratio returns 100 whenever one name is a token subset of the other,
so a bare "Indiana" scores 100 against Indiana State Sycamores exactly as it
does against the Indiana Hoosiers. With "Illinois" in the same position, the
stream "Indiana vs Illinois" tied both games and the winner came down to
start time. The stream's words ARE the Hoosiers' and the Illini's short
names; that settles the tie.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.team_matcher import _exact_sides
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

TODAY = datetime.now(UTC).date()
LEAGUE = "college-football"


def _team(name, short, abbr):
    return Team(
        id=name.lower().replace(" ", "-"), provider="espn", name=name,
        short_name=short, abbreviation=abbr, league=LEAGUE, sport="football",
    )


def _event(home, away, eid, hour=23):
    start = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC).replace(hour=hour)
    return Event(
        id=eid, provider="espn", name=f"{away.name} at {home.name}",
        short_name=f"{away.abbreviation} @ {home.abbreviation}", start_time=start,
        home_team=home, away_team=away, status=EventStatus(state="scheduled"),
        league=LEAGUE, sport="football",
    )


INDIANA = _team("Indiana Hoosiers", "Indiana", "IU")
ILLINOIS = _team("Illinois Fighting Illini", "Illinois", "ILL")
INDIANA_ST = _team("Indiana State Sycamores", "Indiana St", "INST")
ILLINOIS_ST = _team("Illinois State Redbirds", "Illinois St", "ILST")

HOOSIERS_GAME = _event(INDIANA, ILLINOIS, "big-ten")
STATE_GAME = _event(INDIANA_ST, ILLINOIS_ST, "mvfc")


def _match(stream_name, events):
    cache = MagicMock()
    cache.get.return_value = None
    cache.is_failed_cached.return_value = None
    service = MagicMock()
    service.get_team_schedule.return_value = []
    matcher = make_team_matcher(service=service, cache=cache, include_leagues={LEAGUE})
    result = matcher.match_multi_league(
        classified=classify_stream(stream_name),
        enabled_leagues=[LEAGUE],
        target_date=TODAY,
        group_id=1,
        stream_id=1,
        generation=1,
        user_tz=ZoneInfo("UTC"),
        prefetched_events={LEAGUE: events},
    )
    return getattr(result, "event", None)


@pytest.mark.parametrize("order", ["state first", "hoosiers first"])
def test_bare_names_go_to_the_teams_they_name(order):
    events = [STATE_GAME, HOOSIERS_GAME] if order == "state first" else [HOOSIERS_GAME, STATE_GAME]
    matched = _match("Indiana vs Illinois", events)
    assert matched is not None and matched.id == "big-ten"


def test_the_longer_names_still_reach_their_own_game():
    matched = _match("Indiana State vs Illinois State", [HOOSIERS_GAME, STATE_GAME])
    assert matched is not None and matched.id == "mvfc"


def test_a_lone_candidate_is_never_rejected():
    """A tie-break only: with one game on the slate the subset match stands."""
    matched = _match("Indiana vs Illinois", [STATE_GAME])
    assert matched is not None and matched.id == "mvfc"


def test_same_teams_twice_still_falls_to_the_time_rules():
    """A doubleheader ties on exactness and is settled as before."""
    early, late = _event(INDIANA, ILLINOIS, "g1", hour=17), _event(INDIANA, ILLINOIS, "g2", hour=23)
    assert _exact_sides("indiana", "illinois", early) == _exact_sides("indiana", "illinois", late)


def test_exact_sides_counts_either_orientation():
    assert _exact_sides("indiana", "illinois", HOOSIERS_GAME) == 2
    assert _exact_sides("illinois", "indiana", HOOSIERS_GAME) == 2
    assert _exact_sides("indiana", "illinois", STATE_GAME) == 0
    assert _exact_sides("indiana", "purdue", HOOSIERS_GAME) == 1
