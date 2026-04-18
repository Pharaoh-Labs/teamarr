"""Tests for feed team template variables (PR #187).

Verifies that {feed_team}, {feed_team_short}, {feed_team_abbrev},
{feed_team_abbrev_lower}, {feed_team_logo}, {is_home_feed},
{is_away_feed}, and {feed_home_away} extract correctly.
"""

from datetime import UTC, datetime

from teamarr.core import Event, EventStatus, Team
from teamarr.templates.context import (
    GameContext,
    TeamChannelContext,
    TemplateContext,
)
from teamarr.templates.variables.home_away import (
    extract_feed_home_away,
    extract_feed_team,
    extract_feed_team_abbrev,
    extract_feed_team_abbrev_lower,
    extract_feed_team_logo,
    extract_feed_team_short,
    extract_is_away_feed,
    extract_is_home_feed,
)


def _make_team(
    team_id: str,
    name: str,
    short_name: str,
    abbreviation: str,
    logo_url: str | None = None,
) -> Team:
    return Team(
        id=team_id,
        provider="espn",
        name=name,
        short_name=short_name,
        abbreviation=abbreviation,
        league="mlb",
        sport="baseball",
        logo_url=logo_url,
    )


HOME = _make_team("1", "Baltimore Orioles", "Orioles", "BAL", "https://example.com/bal.png")
AWAY = _make_team("2", "New York Yankees", "Yankees", "NYY", "https://example.com/nyy.png")


def _make_event() -> Event:
    return Event(
        id="401999",
        provider="espn",
        name="New York Yankees at Baltimore Orioles",
        short_name="NYY @ BAL",
        start_time=datetime(2026, 7, 15, 19, 5, tzinfo=UTC),
        home_team=HOME,
        away_team=AWAY,
        status=EventStatus(state="scheduled"),
        league="mlb",
        sport="baseball",
    )


def _context_with_feed(
    feed_team: Team | None, event: Event | None = None,
) -> tuple[TemplateContext, GameContext | None]:
    game_ctx = None
    if event:
        game_ctx = GameContext(
            event=event,
            is_home=True,
            team=event.home_team,
            opponent=event.away_team,
        )
    ctx = TemplateContext(
        game_context=game_ctx,
        team_config=TeamChannelContext(
            team_id=HOME.id,
            league="mlb",
            sport="baseball",
            team_name=HOME.name,
        ),
        team_stats=None,
        feed_team=feed_team,
    )
    return ctx, game_ctx


# =============================================================================
# No feed team = "National" for name/abbrev, empty for directional
# =============================================================================


class TestNoFeedTeam:
    """Name/abbrev variables return 'National'; directional variables stay empty."""

    def test_feed_team(self):
        ctx, gc = _context_with_feed(None, _make_event())
        assert extract_feed_team(ctx, gc) == "National"

    def test_feed_team_short(self):
        ctx, gc = _context_with_feed(None, _make_event())
        assert extract_feed_team_short(ctx, gc) == "National"

    def test_feed_team_abbrev(self):
        ctx, gc = _context_with_feed(None, _make_event())
        assert extract_feed_team_abbrev(ctx, gc) == "NATL"

    def test_feed_team_abbrev_lower(self):
        ctx, gc = _context_with_feed(None, _make_event())
        assert extract_feed_team_abbrev_lower(ctx, gc) == "natl"

    def test_feed_team_logo(self):
        ctx, gc = _context_with_feed(None, _make_event())
        assert extract_feed_team_logo(ctx, gc) == ""

    def test_is_home_feed(self):
        ctx, gc = _context_with_feed(None, _make_event())
        assert extract_is_home_feed(ctx, gc) == ""

    def test_is_away_feed(self):
        ctx, gc = _context_with_feed(None, _make_event())
        assert extract_is_away_feed(ctx, gc) == ""

    def test_feed_home_away(self):
        ctx, gc = _context_with_feed(None, _make_event())
        assert extract_feed_home_away(ctx, gc) == ""


# =============================================================================
# Home feed
# =============================================================================


class TestHomeFeed:
    """Feed team is the home team."""

    def test_feed_team_name(self):
        ctx, gc = _context_with_feed(HOME, _make_event())
        assert extract_feed_team(ctx, gc) == "Baltimore Orioles"

    def test_feed_team_short(self):
        ctx, gc = _context_with_feed(HOME, _make_event())
        assert extract_feed_team_short(ctx, gc) == "Orioles"

    def test_feed_team_abbrev(self):
        ctx, gc = _context_with_feed(HOME, _make_event())
        assert extract_feed_team_abbrev(ctx, gc) == "BAL"

    def test_feed_team_abbrev_lower(self):
        ctx, gc = _context_with_feed(HOME, _make_event())
        assert extract_feed_team_abbrev_lower(ctx, gc) == "bal"

    def test_feed_team_logo(self):
        ctx, gc = _context_with_feed(HOME, _make_event())
        assert extract_feed_team_logo(ctx, gc) == "https://example.com/bal.png"

    def test_is_home_feed(self):
        ctx, gc = _context_with_feed(HOME, _make_event())
        assert extract_is_home_feed(ctx, gc) == "true"

    def test_is_away_feed(self):
        ctx, gc = _context_with_feed(HOME, _make_event())
        assert extract_is_away_feed(ctx, gc) == "false"

    def test_feed_home_away(self):
        ctx, gc = _context_with_feed(HOME, _make_event())
        assert extract_feed_home_away(ctx, gc) == "Home"


# =============================================================================
# Away feed
# =============================================================================


class TestAwayFeed:
    """Feed team is the away team."""

    def test_feed_team_name(self):
        ctx, gc = _context_with_feed(AWAY, _make_event())
        assert extract_feed_team(ctx, gc) == "New York Yankees"

    def test_feed_team_short(self):
        ctx, gc = _context_with_feed(AWAY, _make_event())
        assert extract_feed_team_short(ctx, gc) == "Yankees"

    def test_feed_team_abbrev(self):
        ctx, gc = _context_with_feed(AWAY, _make_event())
        assert extract_feed_team_abbrev(ctx, gc) == "NYY"

    def test_feed_team_abbrev_lower(self):
        ctx, gc = _context_with_feed(AWAY, _make_event())
        assert extract_feed_team_abbrev_lower(ctx, gc) == "nyy"

    def test_feed_team_logo(self):
        ctx, gc = _context_with_feed(AWAY, _make_event())
        assert extract_feed_team_logo(ctx, gc) == "https://example.com/nyy.png"

    def test_is_home_feed(self):
        ctx, gc = _context_with_feed(AWAY, _make_event())
        assert extract_is_home_feed(ctx, gc) == "false"

    def test_is_away_feed(self):
        ctx, gc = _context_with_feed(AWAY, _make_event())
        assert extract_is_away_feed(ctx, gc) == "true"

    def test_feed_home_away(self):
        ctx, gc = _context_with_feed(AWAY, _make_event())
        assert extract_feed_home_away(ctx, gc) == "Away"


# =============================================================================
# Edge cases
# =============================================================================


class TestFeedTeamEdgeCases:
    """Edge cases: no game context, missing fields."""

    def test_no_game_context_basic_vars_still_work(self):
        """feed_team/short/abbrev don't need game_ctx."""
        ctx, _ = _context_with_feed(HOME)
        assert extract_feed_team(ctx, None) == "Baltimore Orioles"
        assert extract_feed_team_short(ctx, None) == "Orioles"
        assert extract_feed_team_abbrev(ctx, None) == "BAL"
        assert extract_feed_team_logo(ctx, None) == "https://example.com/bal.png"

    def test_no_feed_team_no_game_context_returns_national(self):
        """Without feed_team or game_ctx, name vars return 'National'."""
        ctx, _ = _context_with_feed(None)
        assert extract_feed_team(ctx, None) == "National"
        assert extract_feed_team_short(ctx, None) == "National"
        assert extract_feed_team_abbrev(ctx, None) == "NATL"

    def test_no_game_context_home_away_empty(self):
        """is_home/is_away/home_away need game_ctx to determine direction."""
        ctx, _ = _context_with_feed(HOME)
        assert extract_is_home_feed(ctx, None) == ""
        assert extract_is_away_feed(ctx, None) == ""
        assert extract_feed_home_away(ctx, None) == ""

    def test_no_logo(self):
        team_no_logo = _make_team("3", "Tampa Bay Rays", "Rays", "TB")
        ctx, gc = _context_with_feed(team_no_logo, _make_event())
        assert extract_feed_team_logo(ctx, gc) == ""

    def test_short_name_fallback_to_name(self):
        """When short_name is empty, falls back to full name."""
        team_no_short = _make_team("4", "Tampa Bay Rays", "", "TB")
        ctx, _ = _context_with_feed(team_no_short)
        assert extract_feed_team_short(ctx, None) == "Tampa Bay Rays"
