"""All-Star game classification and matching (issue #433).

ESPN carries All-Star games inside the normal league scoreboard as two
pseudo-teams whose names both carry an "All-Star(s)" token (MLB:
"American All-Stars"/"National All-Stars"; MLS: "MLS All-Stars"/"Liga MX
All-Stars"). Generically-named streams ("MLB All-Star Game") must route to the
name-agnostic All-Star matcher rather than falling through to TEAM_ONLY.
"""

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import StreamCategory, classify_stream
from teamarr.consumers.matching.result import MatchMethod
from teamarr.consumers.matching.team_matcher import is_all_star_event
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_stream_matcher, make_team_matcher

# ESPN lists the MLB All-Star Game at 23:00 UTC on 2026-07-14.
_ASG_START = datetime(2026, 7, 14, 23, 0, tzinfo=UTC)


def _team(name: str, league: str = "mlb", sport: str = "baseball") -> Team:
    return Team(
        id=name,
        provider="espn",
        name=name,
        short_name=name,
        abbreviation="",
        league=league,
        sport=sport,
    )


def _event(
    home: str,
    away: str,
    *,
    event_id: str = "1",
    league: str = "mlb",
    sport: str = "baseball",
) -> Event:
    return Event(
        id=event_id,
        provider="espn",
        name=f"{away} at {home}",
        short_name="",
        start_time=_ASG_START,
        home_team=_team(home, league, sport),
        away_team=_team(away, league, sport),
        status=EventStatus(state="scheduled"),
        league=league,
        sport=sport,
    )


# --- Classification -------------------------------------------------------


def test_generic_mlb_all_star_stream_classifies_all_star():
    c = classify_stream("MLB All-Star Game")
    assert c.category is StreamCategory.ALL_STAR
    assert c.league_hint == "mlb"


def test_generic_mls_all_star_stream_classifies_all_star():
    c = classify_stream("MLS All-Star Game")
    assert c.category is StreamCategory.ALL_STAR
    assert c.league_hint == "usa.1"


def test_hinted_all_star_matchup_routes_all_star_not_partial_team():
    # Without the All-Star step this yields a partial team1="All-Stars".
    c = classify_stream("MLS All-Stars vs Liga MX All-Stars")
    assert c.category is StreamCategory.ALL_STAR


def test_unhinted_all_star_matchup_falls_through_to_team_vs_team():
    # No league hint → All-Star step abstains; the normal team-vs-team path
    # still resolves it against the group's configured leagues.
    c = classify_stream("American All-Stars vs National All-Stars")
    assert c.category is StreamCategory.TEAM_VS_TEAM


def test_regular_game_is_not_all_star():
    assert classify_stream("Yankees vs Red Sox").category is StreamCategory.TEAM_VS_TEAM


# --- Event predicate ------------------------------------------------------


def test_is_all_star_event_true_when_both_sides_are_all_stars():
    assert is_all_star_event(_event("National All-Stars", "American All-Stars"))
    assert is_all_star_event(
        _event("MLS All-Stars", "Liga MX All-Stars", league="usa.1", sport="soccer")
    )


def test_is_all_star_event_false_for_regular_game():
    assert not is_all_star_event(_event("New York Yankees", "Boston Red Sox"))


def test_is_all_star_event_false_when_only_one_side_all_star():
    assert not is_all_star_event(
        _event("MLS All-Stars", "LA Galaxy", league="usa.1", sport="soccer")
    )


# --- End-to-end matching --------------------------------------------------


def test_match_all_star_resolves_generic_stream_to_event():
    matcher = make_team_matcher()
    event = _event("National All-Stars", "American All-Stars", event_id="as")
    outcomes = matcher.match_all_star(
        classified=classify_stream("MLB All-Star Game"),
        enabled_leagues=["mlb"],
        target_date=date(2026, 7, 14),
        group_id=1,
        stream_id=1,
        generation=1,
        user_tz=ZoneInfo("UTC"),
        prefetched_events={"mlb": [event]},
    )
    assert len(outcomes) == 1
    assert outcomes[0].is_matched
    assert outcomes[0].event.id == "as"
    assert outcomes[0].match_method is MatchMethod.FUZZY


def test_match_all_star_ignores_regular_games_in_pool():
    matcher = make_team_matcher()
    regular = _event("New York Yankees", "Boston Red Sox", event_id="reg")
    allstar = _event("National All-Stars", "American All-Stars", event_id="as")
    outcomes = matcher.match_all_star(
        classified=classify_stream("MLB All-Star Game"),
        enabled_leagues=["mlb"],
        target_date=date(2026, 7, 14),
        group_id=1,
        stream_id=1,
        generation=1,
        user_tz=ZoneInfo("UTC"),
        prefetched_events={"mlb": [regular, allstar]},
    )
    assert len(outcomes) == 1
    assert outcomes[0].event.id == "as"


def test_match_all_star_filters_when_league_not_enabled():
    matcher = make_team_matcher()
    outcomes = matcher.match_all_star(
        classified=classify_stream("MLB All-Star Game"),
        enabled_leagues=["nba"],
        target_date=date(2026, 7, 14),
        group_id=1,
        stream_id=1,
        generation=1,
        user_tz=ZoneInfo("UTC"),
        prefetched_events={},
    )
    assert len(outcomes) == 1
    assert not outcomes[0].is_matched


# --- EPG program-matching path (anchored) ---------------------------------
#
# The EPG path (_compute_epg_plan) feeds each program title through the same
# _route_to_outcomes with anchor_dt = the program's broadcast instant. An
# All-Star program title ("MLB All-Star Game" on FOX) must reach _match_all_star
# and bind only to the occurrence airing near that instant.


def _kwargs():
    return dict(
        enabled_leagues=["mlb"],
        target_date=date(2026, 7, 14),
        group_id=1,
        stream_id=1,
        generation=1,
        user_tz=ZoneInfo("UTC"),
    )


def test_match_all_star_binds_within_anchor_window():
    matcher = make_team_matcher()
    event = _event("National All-Stars", "American All-Stars", event_id="as")
    outcomes = matcher.match_all_star(
        classified=classify_stream("MLB All-Star Game"),
        prefetched_events={"mlb": [event]},
        # Program slot 30 min after event start — inside the 90-min window.
        anchor_dt=_ASG_START + timedelta(minutes=30),
        **_kwargs(),
    )
    assert len(outcomes) == 1
    assert outcomes[0].is_matched
    assert outcomes[0].event.id == "as"


def test_match_all_star_rejects_outside_anchor_window():
    matcher = make_team_matcher()
    event = _event("National All-Stars", "American All-Stars", event_id="as")
    outcomes = matcher.match_all_star(
        classified=classify_stream("MLB All-Star Game"),
        prefetched_events={"mlb": [event]},
        # Program slot 4 hours off (e.g. a next-day encore) — no live bind.
        anchor_dt=_ASG_START + timedelta(hours=4),
        **_kwargs(),
    )
    assert len(outcomes) == 1
    assert not outcomes[0].is_matched


def test_epg_route_reaches_all_star_matcher():
    # Drive the real StreamMatcher routing (what the EPG plan uses) end-to-end.
    matcher = make_stream_matcher(leagues=["mlb"])
    matcher._prefetched_events = {
        "mlb": [_event("National All-Stars", "American All-Stars", event_id="as")]
    }
    outcomes = matcher._route_to_outcomes(
        classify_stream("MLB All-Star Game"),
        stream_id=1,
        target_date=date(2026, 7, 14),
        anchor_dt=_ASG_START,
    )
    assert len(outcomes) == 1
    assert outcomes[0].is_matched
    assert outcomes[0].event.id == "as"
