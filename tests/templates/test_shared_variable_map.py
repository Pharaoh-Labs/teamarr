"""A pre-built variable map must resolve identically to rebuilding per field.

`resolve()` runs all 252 registered extractors (plus `.next`/`.last` suffixes)
on every call, and one programme resolves five to eight fields against a
context that does not change between them. Callers now build the map once and
pass it down, so the equivalence of the two paths is load-bearing.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from teamarr.core.types import Event, EventStatus, Team
from teamarr.services import league_mappings as lm
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.resolver import TemplateResolver


@pytest.fixture(autouse=True)
def real_league_service(db_factory):
    prior = lm._league_mapping_service
    lm.init_league_mapping_service(db_factory)
    yield
    lm._league_mapping_service = prior


@pytest.fixture
def context() -> TemplateContext:
    common = dict(provider="espn", league="nba", sport="basketball")
    event = Event(
        id="1", provider="espn", name="Miami Heat at Boston Celtics",
        short_name="MIA @ BOS",
        start_time=datetime(2026, 6, 17, 23, 0, tzinfo=UTC),
        league="nba", sport="basketball", status=EventStatus(state="pre"),
        home_team=Team(id="1", name="Boston Celtics", short_name="Celtics",
                       abbreviation="BOS", **common),
        away_team=Team(id="2", name="Miami Heat", short_name="Heat",
                       abbreviation="MIA", **common),
    )
    return TemplateContext(
        game_context=GameContext(event=event),
        team_config=TeamChannelContext(team_id="1", league="nba", sport="basketball",
                                       team_name="Boston Celtics"),
        team_stats=None,
    )


TEMPLATES = [
    "{away_team} at {home_team}",
    "{league_name} — {game_time}",
    "{away_team_pascal} visit {home_team|slug}",
    "Plain text with no variables",
    "{definitely_not_a_variable}",
    "{game_time.next}",
    "",
]


@pytest.mark.parametrize("template", TEMPLATES)
def test_shared_map_matches_per_call_build(context, template):
    resolver = TemplateResolver()
    variables = resolver.build_variables(context)
    assert resolver.resolve(template, context, variables=variables) == resolver.resolve(
        template, context
    )


def test_resolve_art_accepts_a_shared_map(context):
    resolver = TemplateResolver("http://art.example")
    variables = resolver.build_variables(context)
    template = "/{league}/{home_team|slug}.png"
    assert resolver.resolve_art(template, context, variables=variables) == (
        resolver.resolve_art(template, context)
    )


def test_extra_vars_reach_a_shared_map(context):
    """The map is built after the caller finishes populating the context, so
    injected variables must be in it."""
    context.extra_vars = {"exception_keyword": "Spanish"}
    resolver = TemplateResolver()
    variables = resolver.build_variables(context)
    assert (
        resolver.resolve("{exception_keyword}", context, variables=variables) == "Spanish"
    )


def test_build_variables_covers_the_whole_registry(context):
    resolver = TemplateResolver()
    variables = resolver.build_variables(context)
    assert len(variables) >= resolver.get_variable_count()
