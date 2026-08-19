"""Regression tests for #510: combat variables must work for boxing.

Every combat extractor and condition was hard-gated on ``sport == "mma"``,
so boxing events (sport == "boxing", served by TSDB) rendered ALL combat
variables empty — even fighter/matchup/title, whose backing fields the TSDB
provider populates by parsing fighters out of the event name. The gate is now
the COMBAT_SPORTS set; card/result variables stay empty for boxing because
only ESPN UFC data carries bouts/results.
"""

from datetime import UTC, datetime

from teamarr.core.types import Event, EventStatus, Team
from teamarr.templates.conditions import ConditionEvaluator
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.variables import get_registry


def _fighter(name: str, id_: str) -> Team:
    return Team(
        id=id_,
        provider="tsdb",
        name=name,
        short_name=name.split()[-1],
        abbreviation=name.split()[-1][:3].upper(),
        league="boxing",
        sport="boxing",
    )


def _boxing_event() -> Event:
    # Shape the TSDB provider produces for boxing: fighters parsed from the
    # event name into home/away; no bouts, results, records, or weight class.
    return Event(
        id="2070000",
        provider="tsdb",
        name="Errol Spence Jr. vs Tim Tszyu",
        short_name="SPE vs TSZ",
        start_time=datetime(2026, 8, 1, 2, 0, tzinfo=UTC),
        home_team=_fighter("Errol Spence Jr.", "2070000_1"),
        away_team=_fighter("Tim Tszyu", "2070000_2"),
        status=EventStatus(state="pre"),
        league="boxing",
        sport="boxing",
    )


def _ctx(event: Event) -> tuple[TemplateContext, GameContext]:
    game = GameContext(
        event=event, is_home=True, team=event.home_team, opponent=event.away_team
    )
    ctx = TemplateContext(
        game_context=game,
        team_config=TeamChannelContext(
            team_id="2070000_1",
            league="boxing",
            sport="boxing",
            team_name="Errol Spence Jr.",
        ),
        team_stats=None,
        team=event.home_team,
    )
    return ctx, game


def _extract(name: str, ctx, game_ctx) -> str:
    definition = get_registry().get(name)
    assert definition is not None, f"variable {name} not registered"
    return definition.extractor(ctx, game_ctx)


def test_fighter_and_title_vars_populate_for_boxing():
    ctx, game = _ctx(_boxing_event())
    assert _extract("fighter1", ctx, game) == "Errol Spence Jr."
    assert _extract("fighter2", ctx, game) == "Tim Tszyu"
    assert _extract("event_title", ctx, game) == "Errol Spence Jr. vs Tim Tszyu"
    assert _extract("matchup_combat", ctx, game) == "Errol Spence Jr. vs Tim Tszyu"
    assert _extract("fighter1_last", ctx, game) != ""
    assert _extract("fighter2_last", ctx, game) != ""


def test_dataless_combat_vars_stay_empty_for_boxing():
    # TSDB has no card composition/result data — these must degrade to "".
    ctx, game = _ctx(_boxing_event())
    for var in ("fight_card", "bout_count", "weight_class", "fight_result", "judge_scores"):
        assert _extract(var, ctx, game) == ""
    # UFC-specific numbering must not misfire on boxing names.
    assert _extract("event_number", ctx, game) == ""


def test_combat_conditions_safe_for_boxing():
    ctx, game = _ctx(_boxing_event())
    evaluator = ConditionEvaluator()
    for cond in ("is_knockout", "is_submission", "is_decision", "is_finish", "went_distance"):
        assert getattr(evaluator, f"_eval_{cond}")(None, ctx, game) is False
