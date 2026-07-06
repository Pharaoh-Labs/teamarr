"""Tests for feed team template variables (PR #187) + broadcast feed labels (#195).

Verifies that {feed_team}, {feed_team_short}, {feed_team_abbrev},
{feed_team_abbrev_lower}, {feed_team_logo}, {is_home_feed}, {is_away_feed},
{feed_home_away}, {broadcast_feed}, and {broadcast_feed_team} extract
correctly for the three feed states (none / home team / away team).
"""

from datetime import UTC, datetime

import pytest

from teamarr.core import Event, EventStatus, Team
from teamarr.templates.context import (
    GameContext,
    TeamChannelContext,
    TemplateContext,
)
from teamarr.templates.variables.home_away import (
    extract_broadcast_feed,
    extract_broadcast_feed_team,
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
    feed_team: Team | None,
    event: Event | None = None,
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


# (extractor, value when feed=HOME, value when feed=AWAY); feed=None is always "".
_GRID = [
    (extract_feed_team, "Baltimore Orioles", "New York Yankees"),
    (extract_feed_team_short, "Orioles", "Yankees"),
    (extract_feed_team_abbrev, "BAL", "NYY"),
    (extract_feed_team_abbrev_lower, "bal", "nyy"),
    (extract_feed_team_logo, "https://example.com/bal.png", "https://example.com/nyy.png"),
    (extract_is_home_feed, "true", "false"),
    (extract_is_away_feed, "false", "true"),
    (extract_feed_home_away, "Home", "Away"),
    (extract_broadcast_feed, "Home Team Feed", "Away Team Feed"),
    (extract_broadcast_feed_team, "Baltimore Orioles Feed", "New York Yankees Feed"),
]


@pytest.mark.parametrize("feed", ["none", "home", "away"])
@pytest.mark.parametrize(
    "extract,home_value,away_value",
    [pytest.param(*row, id=row[0].__name__) for row in _GRID],
)
def test_feed_variable_grid(extract, home_value, away_value, feed):
    team = {"none": None, "home": HOME, "away": AWAY}[feed]
    expected = {"none": "", "home": home_value, "away": away_value}[feed]
    ctx, gc = _context_with_feed(team, _make_event())
    assert extract(ctx, gc) == expected


# ---------------------------------------------------------------------------
# Edge cases: no game context, missing fields
# ---------------------------------------------------------------------------


def test_no_game_context_basic_vars_still_work():
    """feed_team/short/abbrev don't need game_ctx."""
    ctx, _ = _context_with_feed(HOME)
    assert extract_feed_team(ctx, None) == "Baltimore Orioles"
    assert extract_feed_team_short(ctx, None) == "Orioles"
    assert extract_feed_team_abbrev(ctx, None) == "BAL"
    assert extract_feed_team_logo(ctx, None) == "https://example.com/bal.png"


def test_no_game_context_home_away_empty():
    """is_home/is_away/home_away need game_ctx to determine direction."""
    ctx, _ = _context_with_feed(HOME)
    assert extract_is_home_feed(ctx, None) == ""
    assert extract_is_away_feed(ctx, None) == ""
    assert extract_feed_home_away(ctx, None) == ""


def test_no_logo():
    team_no_logo = _make_team("3", "Tampa Bay Rays", "Rays", "TB")
    ctx, gc = _context_with_feed(team_no_logo, _make_event())
    assert extract_feed_team_logo(ctx, gc) == ""


def test_short_name_fallback_to_name():
    """When short_name is empty, falls back to full name."""
    team_no_short = _make_team("4", "Tampa Bay Rays", "", "TB")
    ctx, _ = _context_with_feed(team_no_short)
    assert extract_feed_team_short(ctx, None) == "Tampa Bay Rays"


def test_broadcast_feed_no_game_context_returns_empty():
    # Without game_ctx we can't tell home vs away, so render nothing
    # and let the resolver's whitespace cleanup drop the orphan phrase.
    ctx, _ = _context_with_feed(HOME)
    assert extract_broadcast_feed(ctx, None) == ""


def test_broadcast_feed_team_no_game_context_still_works():
    # Unlike broadcast_feed, this only needs feed_team — no home/away check.
    ctx, _ = _context_with_feed(HOME)
    assert extract_broadcast_feed_team(ctx, None) == "Baltimore Orioles Feed"
