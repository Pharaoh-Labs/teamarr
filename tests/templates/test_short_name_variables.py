"""Tests for team short_name template variables (teamarrv2-d33).

Verifies that {team_short}, {opponent_short}, {matchup_short},
{home_team_short}, and {away_team_short} extract correctly
in both team and event template contexts.
"""

from datetime import UTC, datetime

from teamarr.core import Event, EventStatus, Team
from teamarr.templates.context import (
    GameContext,
    TeamChannelContext,
    TemplateContext,
)
from teamarr.templates.variables.home_away import (
    extract_away_team_short,
    extract_home_team_short,
)
from teamarr.templates.variables.identity import (
    extract_matchup_short,
    extract_opponent_short,
    extract_team_short,
)


def _make_team(
    team_id: str,
    name: str,
    short_name: str,
    abbreviation: str,
) -> Team:
    return Team(
        id=team_id,
        provider="espn",
        name=name,
        short_name=short_name,
        abbreviation=abbreviation,
        league="nfl",
        sport="football",
    )


HOME = _make_team("1", "Detroit Lions", "Lions", "DET")
AWAY = _make_team("2", "Chicago Bears", "Bears", "CHI")


def _make_event() -> Event:
    return Event(
        id="401234",
        provider="espn",
        name="Chicago Bears at Detroit Lions",
        short_name="CHI @ DET",
        start_time=datetime(2026, 1, 5, 18, 0, tzinfo=UTC),
        home_team=HOME,
        away_team=AWAY,
        status=EventStatus(state="scheduled"),
        league="nfl",
        sport="football",
    )


def _team_context(team: Team, event: Event | None = None) -> TemplateContext:
    """Build context from team perspective (team EPG)."""
    game_ctx = None
    if event:
        is_home = event.home_team.id == team.id
        opponent = event.away_team if is_home else event.home_team
        game_ctx = GameContext(
            event=event,
            is_home=is_home,
            team=team,
            opponent=opponent,
        )

    return TemplateContext(
        game_context=game_ctx,
        team_config=TeamChannelContext(
            team_id=team.id,
            league="nfl",
            sport="football",
            team_name=team.name,
            team_abbrev=team.abbreviation,
            team_short_name=team.short_name,
        ),
        team_stats=None,
        team=team,
    )


def _event_context(event: Event) -> TemplateContext:
    """Build context from event perspective (event EPG)."""
    game_ctx = GameContext(
        event=event,
        is_home=True,
        team=event.home_team,
        opponent=event.away_team,
    )
    return TemplateContext(
        game_context=game_ctx,
        team_config=TeamChannelContext(
            team_id=event.home_team.id,
            league="nfl",
            sport="football",
            team_name=event.home_team.name,
            team_abbrev=event.home_team.abbreviation,
            team_short_name=event.home_team.short_name,
        ),
        team_stats=None,
    )


# =============================================================================
# {team_short}
# =============================================================================


class TestTeamShort:
    def test_from_config(self):
        ctx = _team_context(HOME)
        assert extract_team_short(ctx, None) == "Lions"

    def test_empty_when_not_set(self):
        ctx = _team_context(HOME)
        ctx.team_config.team_short_name = None
        assert extract_team_short(ctx, None) == ""

    def test_with_game_context(self):
        event = _make_event()
        ctx = _team_context(HOME, event)
        assert extract_team_short(ctx, ctx.game_context) == "Lions"


# =============================================================================
# {opponent_short}
# =============================================================================


class TestOpponentShort:
    def test_home_perspective(self):
        event = _make_event()
        ctx = _team_context(HOME, event)
        assert extract_opponent_short(ctx, ctx.game_context) == "Bears"

    def test_away_perspective(self):
        event = _make_event()
        ctx = _team_context(AWAY, event)
        assert extract_opponent_short(ctx, ctx.game_context) == "Lions"

    def test_no_event(self):
        ctx = _team_context(HOME)
        assert extract_opponent_short(ctx, None) == ""


# =============================================================================
# {matchup_short}
# =============================================================================


class TestMatchupShort:
    def test_format(self):
        event = _make_event()
        ctx = _team_context(HOME, event)
        assert extract_matchup_short(ctx, ctx.game_context) == "Bears @ Lions"

    def test_no_event(self):
        ctx = _team_context(HOME)
        assert extract_matchup_short(ctx, None) == ""


# =============================================================================
# {home_team_short} / {away_team_short}
# =============================================================================


class TestHomeAwayShort:
    def test_home_team_short(self):
        event = _make_event()
        ctx = _event_context(event)
        assert extract_home_team_short(ctx, ctx.game_context) == "Lions"

    def test_away_team_short(self):
        event = _make_event()
        ctx = _event_context(event)
        assert extract_away_team_short(ctx, ctx.game_context) == "Bears"

    def test_no_event(self):
        ctx = _team_context(HOME)
        assert extract_home_team_short(ctx, None) == ""
        assert extract_away_team_short(ctx, None) == ""


# =============================================================================
# CONTEXT PLUMBING
# =============================================================================


class TestContextPlumbing:
    """Verify TeamChannelContext correctly carries team_short_name."""

    def test_context_field_exists(self):
        config = TeamChannelContext(
            team_id="1",
            league="nfl",
            sport="football",
            team_name="Detroit Lions",
            team_short_name="Lions",
        )
        assert config.team_short_name == "Lions"

    def test_context_field_defaults_none(self):
        config = TeamChannelContext(
            team_id="1",
            league="nfl",
            sport="football",
            team_name="Detroit Lions",
        )
        assert config.team_short_name is None

    def test_soccer_short_names(self):
        """Short names work for soccer teams too."""
        liverpool = _make_team("364", "Liverpool", "Liverpool", "LIV")
        arsenal = _make_team("359", "Arsenal", "Arsenal", "ARS")
        event = Event(
            id="700001",
            provider="espn",
            name="Arsenal vs Liverpool",
            short_name="ARS vs LIV",
            start_time=datetime(2026, 3, 8, 15, 0, tzinfo=UTC),
            home_team=arsenal,
            away_team=liverpool,
            status=EventStatus(state="scheduled"),
            league="eng.1",
            sport="soccer",
        )
        ctx = _event_context(event)
        assert extract_home_team_short(ctx, ctx.game_context) == "Arsenal"
        assert extract_away_team_short(ctx, ctx.game_context) == "Liverpool"
        assert extract_matchup_short(ctx, ctx.game_context) == "Liverpool @ Arsenal"
