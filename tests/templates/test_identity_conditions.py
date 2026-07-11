"""league_is / sport_is value-matched conditions (#370 part 1).

One template can branch its description register by league or sport instead
of needing a per-league template variant. Values are comma-separated code
lists, case-insensitive.
"""

from datetime import UTC, datetime

from teamarr.core.types import Event, EventStatus, Team
from teamarr.templates.conditions import ConditionEvaluator
from teamarr.templates.context import (
    GameContext,
    TeamChannelContext,
    TemplateContext,
)


def _event(league: str = "nba", sport: str = "basketball") -> Event:
    team = dict(provider="espn", league=league, sport=sport)
    return Event(
        id="1",
        provider="espn",
        name="A vs B",
        short_name="A @ B",
        start_time=datetime(2026, 6, 17, 19, 0, tzinfo=UTC),
        league=league,
        sport=sport,
        status=EventStatus(state="pre"),
        home_team=Team(id="1", name="Home", short_name="H", abbreviation="H", **team),
        away_team=Team(id="2", name="Away", short_name="A", abbreviation="A", **team),
    )


def _ctx(event: Event) -> tuple[TemplateContext, GameContext]:
    gc = GameContext(event=event)
    tc = TeamChannelContext(
        team_id="1", league=event.league, sport=event.sport, team_name="Home"
    )
    return TemplateContext(game_context=gc, team_config=tc, team_stats=None), gc


def test_league_is_single_code():
    ev = ConditionEvaluator()
    ctx, gc = _ctx(_event(league="cfb", sport="football"))
    assert ev.evaluate("league_is", "cfb", ctx, gc) is True
    assert ev.evaluate("league_is", "nfl", ctx, gc) is False


def test_league_is_comma_separated_and_case_insensitive():
    ev = ConditionEvaluator()
    ctx, gc = _ctx(_event(league="eng.1", sport="soccer"))
    assert ev.evaluate("league_is", "NFL, ENG.1", ctx, gc) is True
    assert ev.evaluate("league_is", "nfl,cfb", ctx, gc) is False


def test_sport_is_matching():
    ev = ConditionEvaluator()
    ctx, gc = _ctx(_event(league="nhl", sport="hockey"))
    assert ev.evaluate("sport_is", "hockey", ctx, gc) is True
    assert ev.evaluate("sport_is", "Basketball,HOCKEY", ctx, gc) is True
    assert ev.evaluate("sport_is", "football", ctx, gc) is False


def test_missing_value_never_matches():
    ev = ConditionEvaluator()
    ctx, gc = _ctx(_event())
    assert ev.evaluate("league_is", None, ctx, gc) is False
    assert ev.evaluate("league_is", "", ctx, gc) is False
    assert ev.evaluate("sport_is", " , ", ctx, gc) is False


def test_conditions_exposed_to_both_template_types():
    from teamarr.api.routes.variables import get_conditions

    for template_type in ("team", "event"):
        names = {c["name"] for c in get_conditions(template_type)["conditions"]}
        assert {"league_is", "sport_is"} <= names
        by_name = {c["name"]: c for c in get_conditions(template_type)["conditions"]}
        assert by_name["league_is"]["requires_value"] is True
        assert by_name["league_is"]["value_type"] == "string"
