"""is_final / is_not_final condition evaluators (#420, epic cajd).

The disjoint pair exists for faithful final/not-final filler migration:
both must return False with no reference game, and neither may act as the
other's negation-with-fallthrough (an `always` row would wrongly donate its
fields to final games under per-field selection).
"""

from datetime import UTC, datetime

from teamarr.core.types import Event, EventStatus, Team
from teamarr.templates.conditions import ConditionEvaluator
from teamarr.templates.context import (
    GameContext,
    TeamChannelContext,
    TemplateContext,
)


def _event(state: str) -> Event:
    return Event(
        id="1",
        provider="espn",
        name="A vs B",
        short_name="A @ B",
        start_time=datetime(2026, 6, 17, 19, 0, tzinfo=UTC),
        league="nba",
        sport="basketball",
        status=EventStatus(state=state),
        home_team=Team(
            id="1", provider="espn", name="Home Heat", short_name="Heat",
            abbreviation="HH", league="nba", sport="basketball",
        ),
        away_team=Team(
            id="2", provider="espn", name="Away Aces", short_name="Aces",
            abbreviation="AA", league="nba", sport="basketball",
        ),
    )


def _ctx(event: Event | None) -> tuple[TemplateContext, GameContext]:
    gc = GameContext(event=event)
    tc = TeamChannelContext(
        team_id="1", league="nba", sport="basketball", team_name="Home Heat"
    )
    return TemplateContext(game_context=gc, team_config=tc, team_stats=None), gc


def test_is_final_true_for_final_game():
    ev = ConditionEvaluator()
    ctx, gc = _ctx(_event("final"))
    assert ev.evaluate("is_final", None, ctx, gc) is True
    assert ev.evaluate("is_not_final", None, ctx, gc) is False


def test_is_not_final_true_for_in_progress_game():
    ev = ConditionEvaluator()
    ctx, gc = _ctx(_event("in"))
    assert ev.evaluate("is_final", None, ctx, gc) is False
    assert ev.evaluate("is_not_final", None, ctx, gc) is True


def test_both_false_without_reference_game():
    # Neither is the other's negation: no game -> neither state applies.
    ev = ConditionEvaluator()
    ctx, gc = _ctx(None)
    assert ev.evaluate("is_final", None, ctx, gc) is False
    assert ev.evaluate("is_not_final", None, ctx, gc) is False


def test_post_state_counts_as_final():
    ev = ConditionEvaluator()
    ctx, gc = _ctx(_event("post"))
    assert ev.evaluate("is_final", None, ctx, gc) is True
