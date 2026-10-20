"""{knockout_round}, {match_leg}, {aggregate_score} and the two cup-tie conditions (#916)."""

from datetime import datetime

from teamarr.config import set_global_matchup_order
from teamarr.core import SEASON_POSTSEASON
from teamarr.core.types import Event, EventStatus, Team
from teamarr.templates.conditions import ConditionEvaluator
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.variables.soccer import (
    extract_aggregate_score,
    extract_knockout_round,
    extract_match_leg,
)
from teamarr.templates.variables.summary import extract_series_game


def _team(i, name, abbr):
    return Team(
        id=i,
        provider="espn",
        name=name,
        short_name=name,
        abbreviation=abbr,
        league="uefa.champions",
        sport="soccer",
    )


def _event(**kw) -> Event:
    base = dict(
        id="1",
        provider="espn",
        name="Newcastle United at Barcelona",
        short_name="NEW @ BAR",
        start_time=datetime(2026, 3, 18, 20, 0),
        league="uefa.champions",
        sport="soccer",
        status=EventStatus(state="post"),
        home_team=_team("83", "Barcelona", "BAR"),
        away_team=_team("361", "Newcastle United", "NEW"),
        season_type=SEASON_POSTSEASON,
    )
    base.update(kw)
    return Event(**base)


def _ctx(event: Event) -> tuple[TemplateContext, GameContext]:
    gc = GameContext(event=event)
    tc = TeamChannelContext(
        team_id="83", league="uefa.champions", sport="soccer", team_name="Barcelona"
    )
    return TemplateContext(game_context=gc, team_config=tc, team_stats=None), gc


DECIDED = dict(
    knockout_round="Round of 16",
    match_leg=2,
    match_legs_total=2,
    aggregate_home=8,
    aggregate_away=3,
    tie_winner="home",
    game_event_note="2nd Leg - Barcelona advance 8-3 on aggregate",
)


def test_variables_on_a_decided_second_leg():
    tctx, gc = _ctx(_event(**DECIDED))
    assert extract_knockout_round(tctx, gc) == "Round of 16"
    assert extract_match_leg(tctx, gc) == "2nd Leg"
    assert extract_aggregate_score(tctx, gc) == "8-3"  # soccer: home first


def test_aggregate_follows_the_matchup_order_setting():
    set_global_matchup_order("away_first")
    try:
        tctx, gc = _ctx(_event(**DECIDED))
        assert extract_aggregate_score(tctx, gc) == "3-8"
    finally:
        set_global_matchup_order("auto")


def test_first_leg_has_no_aggregate_yet():
    tctx, gc = _ctx(_event(knockout_round="Round of 16", match_leg=1, match_legs_total=2))
    assert extract_match_leg(tctx, gc) == "1st Leg"
    assert extract_aggregate_score(tctx, gc) == ""


def test_final_and_league_phase_render_only_what_they_are():
    tctx, gc = _ctx(_event(knockout_round="Final"))
    assert extract_knockout_round(tctx, gc) == "Final"
    assert extract_match_leg(tctx, gc) == ""
    tctx, gc = _ctx(_event(season_type="regular"))
    assert extract_knockout_round(tctx, gc) == ""
    assert extract_match_leg(tctx, gc) == ""
    assert extract_aggregate_score(tctx, gc) == ""


def test_a_soccer_leg_never_gets_a_game_number_badge():
    """{series_game} reads 'Game N'; a leg note never says that (#916)."""
    tctx, gc = _ctx(_event(**DECIDED))
    assert extract_series_game(tctx, gc) == ""


def test_no_event_is_empty_everywhere():
    tctx = TemplateContext(game_context=None, team_config=None, team_stats=None)
    assert extract_knockout_round(tctx, None) == ""
    assert extract_match_leg(tctx, None) == ""
    assert extract_aggregate_score(tctx, None) == ""


def test_conditions():
    ev = ConditionEvaluator()
    tctx, gc = _ctx(_event(**DECIDED))
    assert ev._eval_has_knockout_round(None, tctx, gc) is True
    assert ev._eval_match_leg(None, tctx, gc) is True
    assert ev._eval_match_leg("2", tctx, gc) is True
    assert ev._eval_match_leg("1", tctx, gc) is False
    assert ev._eval_match_leg("two", tctx, gc) is False

    tctx, gc = _ctx(_event(knockout_round="Final"))
    assert ev._eval_has_knockout_round(None, tctx, gc) is True
    assert ev._eval_match_leg(None, tctx, gc) is False  # a final is not a leg

    tctx, gc = _ctx(_event(season_type="regular"))
    assert ev._eval_has_knockout_round(None, tctx, gc) is False
    assert ev._eval_match_leg("1", tctx, gc) is False
