"""{league_code} on cricket events: the ESPN series slug wins (bead s7ny).

ESPN has no standing cricket leagues — every tour is its own numbered series
("8050", "1554555") — and game-thumbs keys cricket art under that slug, so the
format code ("cricket-t20i") matches nothing there. When the panel supplied a
series slug the variable emits it, digits untouched; every other league — and
any render without an event, like team channels and samples — resolves exactly
as before.
"""

from datetime import UTC, datetime

import pytest

from teamarr.core.types import Event, EventStatus, Team
from teamarr.services import league_mappings as lm
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.resolver import TemplateResolver
from teamarr.templates.variables.identity import extract_league_code


@pytest.fixture
def league_service(db_factory):
    """A real mapping service — a full resolve() runs every extractor."""
    prior = lm._league_mapping_service
    lm.init_league_mapping_service(db_factory)
    yield
    lm._league_mapping_service = prior


def _cricket_event(series_slug: str = "8050") -> Event:
    return Event(
        id="1546541",
        provider="espn",
        name="Sikkim v Meghalaya",
        short_name="SIKM v MEGHA",
        start_time=datetime(2026, 10, 11, 2, 45, tzinfo=UTC),
        home_team=Team(
            id="2085",
            provider="espn",
            name="Sikkim",
            short_name="Sikkim",
            abbreviation="SIKM",
            league="cricket-test",
            sport="cricket",
        ),
        away_team=Team(
            id="2086",
            provider="espn",
            name="Meghalaya",
            short_name="Meghalaya",
            abbreviation="MEGHA",
            league="cricket-test",
            sport="cricket",
        ),
        status=EventStatus(state="live", detail="Stumps"),
        league="cricket-test",
        sport="cricket",
        series_slug=series_slug,
    )


def _ctx(event: Event | None, league: str = "cricket-test") -> TemplateContext:
    game_ctx = GameContext(event=event)
    team_config = TeamChannelContext(team_id="1", league=league, sport="cricket", team_name="X")
    return TemplateContext(game_context=game_ctx, team_config=team_config, team_stats=None)


def test_the_series_slug_wins_and_digits_pass_through():
    ctx = _ctx(_cricket_event("8050"))
    assert extract_league_code(ctx, ctx.game_context) == "8050"

    ctx = _ctx(_cricket_event("1554555"))
    assert extract_league_code(ctx, ctx.game_context) == "1554555"


def test_without_a_slug_the_format_code_stands():
    ctx = _ctx(_cricket_event(""))
    assert extract_league_code(ctx, ctx.game_context) == "cricket-test"


def test_a_render_without_an_event_still_resolves_the_format_code():
    ctx = _ctx(None)
    assert extract_league_code(ctx, ctx.game_context) == "cricket-test"


def test_an_art_path_renders_the_numeric_slug(league_service):
    resolver = TemplateResolver()
    art = resolver.resolve_art(
        "{league_code}/{away_team|pascal}/{home_team|pascal}/cover.png"
        "?style=1&logo=true&fallback=true",
        _ctx(_cricket_event("8050")),
    )
    assert art == "8050/Meghalaya/Sikkim/cover.png?style=1&logo=true&fallback=true"
