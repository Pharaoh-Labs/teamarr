"""Result variables and text mechanics behind the starter style pass (#991)."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from teamarr.core.types import Event, EventStatus, Team
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.resolver import TemplateResolver
from teamarr.templates.variables.scores import (
    extract_event_result_text,
    extract_result_score,
)


@pytest.fixture(autouse=True)
def league_mapping_service():
    svc = MagicMock()
    svc.get_league_alias.side_effect = lambda code: code.upper()
    svc.get_league_display_name.side_effect = lambda code: code.upper()
    with patch("teamarr.services.league_mappings._league_mapping_service", svc):
        yield svc


def _team(id_, name, league="nfl", sport="football"):
    return Team(id=id_, provider="espn", name=name, short_name=name.split()[-1],
                abbreviation=name[:3].upper(), league=league, sport=sport)


def _game(home_score, away_score, state="post", league="nfl", sport="football",
          home="Carolina Panthers", away="Detroit Lions"):
    event = Event(
        id="1", provider="espn", name="x", short_name="x",
        start_time=datetime(2026, 10, 5, 0, 20, tzinfo=UTC), league=league, sport=sport,
        status=EventStatus(state=state), home_team=_team("29", home, league, sport),
        away_team=_team("8", away, league, sport),
        home_score=home_score, away_score=away_score,
    )
    ctx = TemplateContext(
        game_context=GameContext(event=event),
        team_config=TeamChannelContext(team_id="8", league=league, sport=sport, team_name=away),
        team_stats=None,
    )
    return ctx, ctx.game_context


def test_result_score_puts_the_winners_score_first_whoever_won():
    assert extract_result_score(*_game(32, 26)) == "32-26"  # home won
    assert extract_result_score(*_game(26, 32)) == "32-26"  # away won
    assert extract_result_score(*_game(1, 1)) == "1-1"


def test_result_score_is_empty_until_the_game_is_final():
    assert extract_result_score(*_game(14, 7, state="in")) == ""
    assert extract_result_score(*_game(None, None)) == ""


def test_event_result_text_names_the_winner_first():
    assert extract_event_result_text(*_game(32, 26)) == (
        "The Carolina Panthers beat the Detroit Lions, 32-26."
    )
    assert extract_event_result_text(*_game(26, 32)) == (
        "The Detroit Lions beat the Carolina Panthers, 32-26."
    )


def test_event_result_text_handles_a_draw_and_bare_club_names():
    ctx, game = _game(1, 1, league="eng.1", sport="soccer", home="Chelsea", away="Arsenal")
    assert extract_event_result_text(ctx, game) == "Arsenal and Chelsea drew, 1-1."
    ctx, game = _game(2, 1, league="eng.1", sport="soccer", home="Chelsea", away="Arsenal")
    assert extract_event_result_text(ctx, game) == "Chelsea beat Arsenal, 2-1."


def test_event_result_text_is_empty_until_final():
    assert extract_event_result_text(*_game(14, 7, state="in")) == ""


@pytest.mark.parametrize(
    "raw, cleaned",
    [
        # an empty sentence-final variable strands its full stop
        ("at Ford Field. .", "at Ford Field."),
        ("at Ford Field. Series tied 1-1.", "at Ford Field. Series tied 1-1."),
        ("the Lions lost, 32-26 .", "The Lions lost, 32-26."),
        ("the Lions lost, 32-26 in overtime.", "The Lions lost, 32-26 in overtime."),
        # untouched: abbreviations, decimals, ordinary text
        ("Lions vs. Panthers", "Lions vs. Panthers"),
        ("spread of .5 points", "spread of .5 points"),
        # an article-aware name opening a later sentence takes its capital…
        ("NBA Finals - Game 5. the Pistons and the Celtics meet.",
         "NBA Finals - Game 5. The Pistons and the Celtics meet."),
        # …but "vs." is a connector, not a sentence end
        ("Next game: vs. the Ottawa Senators", "Next game: vs. the Ottawa Senators"),
    ],
)
def test_cleanup_pulls_a_stranded_full_stop_back_in(raw, cleaned):
    assert TemplateResolver()._cleanup_result(raw) == cleaned


def test_default_event_line_drops_the_article_for_a_national_team():
    """The Default starters are the catch-all — UEFA Nations League lands on
    them. "The Cyprus (1-1-1) host the Latvia (0-1-2)" was the first cut."""
    from teamarr.database.default_templates import DEFAULT_TEMPLATE_SET

    spec = next(s for s in DEFAULT_TEMPLATE_SET if s["name"] == "Default Event (Starter)")
    default_row = next(r for r in spec["conditional_descriptions"] if r["label"] == "Default")
    ctx, _ = _game(None, None, state="pre", league="uefa.nations", sport="soccer",
                   home="Cyprus", away="Latvia")
    assert TemplateResolver().resolve(default_row["template"], ctx) == "Cyprus host Latvia at."

    ctx, _ = _game(None, None, state="pre")
    assert TemplateResolver().resolve(default_row["template"], ctx) == (
        "The Carolina Panthers host the Detroit Lions at."
    )


@pytest.mark.parametrize(
    "summary, is_state",
    [
        ("Series tied 1-1", True),
        ("BOS leads series 3-2", True),
        ("Series starts 12/16", False),
        ("series starts 10/6", False),
        ("", False),
        (None, False),
    ],
)
def test_a_series_that_has_not_begun_is_not_series_state(summary, is_state):
    from teamarr.providers.espn.preview import is_series_state

    assert is_series_state(summary) is is_state


def test_select_series_skips_a_series_that_has_not_begun():
    from teamarr.providers.espn.preview import select_series

    assert select_series([{"type": "season", "summary": "Series starts 12/16"}]) is None
    chosen = select_series(
        [{"type": "season", "summary": "Series starts 12/16"},
         {"type": "season", "summary": "Series tied 1-1"}]
    )
    assert chosen["summary"] == "Series tied 1-1"
