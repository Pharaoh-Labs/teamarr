"""Tests for the summary/context variables (tvnk.10 free tier).

Covers the type-keyed headline selection + EPG-friendly text extraction in the
ESPN provider (shortLinkText preference, dateline-dash strip) and the
passthrough extractors: game_recap, game_event_note, soccer_match_note.
"""

from datetime import datetime

from teamarr.config import set_global_matchup_order
from teamarr.core import SEASON_POSTSEASON, SEASON_REGULAR
from teamarr.core.types import Event, EventStatus, Team
from teamarr.providers.espn.provider import ESPNProvider
from teamarr.templates.context import (
    GameContext,
    TeamChannelContext,
    TemplateContext,
)
from teamarr.templates.variables.soccer import extract_soccer_match_note
from teamarr.templates.variables.summary import (
    extract_game_event_note,
    extract_game_preview,
    extract_game_recap,
    extract_series_game,
    extract_series_score,
    extract_series_summary,
    extract_series_summary_short,
)


def _event(**kw) -> Event:
    base = dict(
        id="1",
        provider="espn",
        name="A vs B",
        short_name="A @ B",
        start_time=datetime(2026, 6, 17, 19, 0),
        league="nba",
        sport="basketball",
        status=EventStatus(state="post"),
        home_team=Team(
            id="1",
            provider="espn",
            name="B",
            short_name="B",
            abbreviation="B",
            league="nba",
            sport="basketball",
        ),
        away_team=Team(
            id="2",
            provider="espn",
            name="A",
            short_name="A",
            abbreviation="A",
            league="nba",
            sport="basketball",
        ),
    )
    base.update(kw)
    return Event(**base)


def _ctx(event: Event) -> tuple[TemplateContext, GameContext]:
    gc = GameContext(event=event)
    tc = TeamChannelContext(team_id="1", league="nba", sport="basketball", team_name="B")
    return TemplateContext(game_context=gc, team_config=tc, team_stats=None), gc


# --- type-keyed headline selection + EPG-friendly text extraction (provider logic) ---


def test_headline_of_type_selects_by_tag():
    comp = {
        "headlines": [
            {"type": "Preview", "shortLinkText": "preview text"},
            {"type": "Recap", "shortLinkText": "recap text"},
        ]
    }
    assert ESPNProvider._headline_of_type(comp, "Recap") == "recap text"
    assert ESPNProvider._headline_of_type(comp, "Preview") == "preview text"


def test_headline_of_type_empty_when_absent():
    assert ESPNProvider._headline_of_type({}, "Recap") == ""
    assert ESPNProvider._headline_of_type({"headlines": []}, "Recap") == ""
    assert (
        ESPNProvider._headline_of_type(
            {"headlines": [{"type": "Preview", "shortLinkText": "p"}]}, "Recap"
        )
        == ""
    )


def test_editorial_text_prefers_short_link():
    # The clean headline wins over the long wire body.
    obj = {
        "shortLinkText": "Mets beat Reds 9-1 to avoid sweep",
        "description": "— Bo Bichette continued his hot streak with three hits…",
    }
    assert ESPNProvider._editorial_text(obj) == "Mets beat Reds 9-1 to avoid sweep"


def test_editorial_text_strips_dateline_dash():
    # No shortLinkText → fall back to description with the AP em dash stripped.
    obj = {"description": "— Bo Bichette continued his hot streak with three hits."}
    assert (
        ESPNProvider._editorial_text(obj)
        == "Bo Bichette continued his hot streak with three hits."
    )


def test_editorial_text_leaves_clean_description_untouched():
    # Soccer copy has no dateline dash — must pass through verbatim.
    obj = {"description": "Brighton sealed a European spot despite a Man Utd loss."}
    assert (
        ESPNProvider._editorial_text(obj)
        == "Brighton sealed a European spot despite a Man Utd loss."
    )


def test_editorial_text_empty_when_absent():
    assert ESPNProvider._editorial_text({}) == ""
    assert ESPNProvider._editorial_text({"shortLinkText": "", "description": ""}) == ""


# --- extractors are raw passthrough, empty when absent ---


def test_game_recap_passthrough():
    ctx, gc = _ctx(_event(game_recap="Brunson scored 45."))
    assert extract_game_recap(ctx, gc) == "Brunson scored 45."


def test_game_event_note_passthrough():
    ctx, gc = _ctx(_event(game_event_note="NBA Finals - Game 5"))
    assert extract_game_event_note(ctx, gc) == "NBA Finals - Game 5"


def test_soccer_match_note_passthrough():
    ctx, gc = _ctx(_event(soccer_match_note="FIFA World Cup, Group J"))
    assert extract_soccer_match_note(ctx, gc) == "FIFA World Cup, Group J"


def test_game_preview_passthrough():
    ctx, gc = _ctx(_event(game_preview="Toronto Blue Jays vs. Boston Red Sox"))
    assert extract_game_preview(ctx, gc) == "Toronto Blue Jays vs. Boston Red Sox"


def test_series_summary_passthrough():
    ctx, gc = _ctx(_event(series_summary="Series tied 1-1"))
    assert extract_series_summary(ctx, gc) == "Series tied 1-1"


def test_extractors_empty_when_unset():
    ctx, gc = _ctx(_event())
    for fn in (
        extract_game_recap,
        extract_game_event_note,
        extract_soccer_match_note,
        extract_game_preview,
        extract_series_summary,
        extract_series_game,
        extract_series_score,
        extract_series_summary_short,
    ):
        assert fn(ctx, gc) == ""


def test_extractors_safe_without_event():
    ctx, gc = _ctx(_event())
    ctx.game_context.event = None
    gc = ctx.game_context
    for fn in (
        extract_game_recap,
        extract_game_event_note,
        extract_soccer_match_note,
        extract_game_preview,
        extract_series_summary,
        extract_series_game,
        extract_series_score,
        extract_series_summary_short,
    ):
        assert fn(ctx, gc) == ""


def test_series_game_in_postseason():
    ctx, gc = _ctx(_event(
        season_type=SEASON_POSTSEASON,
        game_event_note="AL Wild Card - Game 2",
    ))
    assert extract_series_game(ctx, gc) == "Game 2"

    ctx2, gc2 = _ctx(_event(
        season_type=SEASON_POSTSEASON,
        game_event_note="Stanley Cup Final - Game 7",
    ))
    assert extract_series_game(ctx2, gc2) == "Game 7"


def test_series_game_empty_in_regular_season():
    ctx, gc = _ctx(_event(
        season_type=SEASON_REGULAR,
        game_event_note="AL Wild Card - Game 2",
    ))
    assert extract_series_game(ctx, gc) == ""


def test_series_game_empty_when_no_game_number():
    ctx, gc = _ctx(_event(
        season_type=SEASON_POSTSEASON,
        game_event_note="Super Bowl LIX",
    ))
    assert extract_series_game(ctx, gc) == ""


def test_series_score_and_summary_short_postseason():
    # Away is A, Home is B
    set_global_matchup_order("auto")
    ctx, gc = _ctx(_event(
        season_type=SEASON_POSTSEASON,
        sport="baseball",
        series_summary="B leads 2-1",
    ))
    # In away-first (baseball auto): A (Away, 1 win) - B (Home, 2 wins) -> "1-2"
    assert extract_series_score(ctx, gc) == "1-2"
    assert extract_series_summary_short(ctx, gc) == "A 1 - B 2"


def test_series_score_and_summary_short_tied():
    ctx, gc = _ctx(_event(
        season_type=SEASON_POSTSEASON,
        sport="baseball",
        series_summary="Series tied 1-1",
    ))
    assert extract_series_score(ctx, gc) == "1-1"
    assert extract_series_summary_short(ctx, gc) == "Tied 1-1"


def test_series_score_and_summary_short_home_first_localization():
    set_global_matchup_order("home_first")
    try:
        ctx, gc = _ctx(_event(
            season_type=SEASON_POSTSEASON,
            sport="baseball",
            series_summary="B leads 2-1",
        ))
        # In home-first: B (Home, 2 wins) - A (Away, 1 win) -> "2-1"
        assert extract_series_score(ctx, gc) == "2-1"
        assert extract_series_summary_short(ctx, gc) == "B 2 - A 1"
    finally:
        set_global_matchup_order("auto")


def test_series_score_and_summary_short_empty_in_regular_season():
    ctx, gc = _ctx(_event(
        season_type=SEASON_REGULAR,
        sport="baseball",
        series_summary="B leads 2-1",
    ))
    assert extract_series_score(ctx, gc) == ""
    assert extract_series_summary_short(ctx, gc) == ""


def test_preview_text_written_preview_uses_headline():
    # A written (AP) preview's description is the story's opening anecdote;
    # the headline is the line that summarises the game (#979).
    article = {
        "type": "Preview",
        "source": "AP",
        "headline": (
            "Panthers defense looks to slow down Jared Goff and the Lions "
            "while missing both starting cornerbacks"
        ),
        "description": (
            "— The Carolina Panthers found themselves in a precarious position last November."
        ),
    }
    assert ESPNProvider._preview_text(article) == article["headline"]


def test_preview_text_generated_preview_keeps_description():
    # Machine-generated previews are the reverse: generic headline, records
    # in the description.
    article = {
        "type": "Preview",
        "source": "Data Skrive",
        "headline": "Southern Miss visits Troy in Sun Belt matchup",
        "description": "Southern Miss (1-3) at Troy (2-2), Oct. 6 at 8 p.m. EDT.",
    }
    assert (
        ESPNProvider._preview_text(article)
        == "Southern Miss (1-3) at Troy (2-2), Oct. 6 at 8 p.m. EDT."
    )


def test_preview_text_unknown_source_uses_headline():
    article = {"headline": "headline", "description": "body"}
    assert ESPNProvider._preview_text(article) == "headline"


def test_preview_text_short_link_still_wins():
    article = {"shortLinkText": "short", "headline": "headline", "description": "body"}
    assert ESPNProvider._preview_text(article) == "short"


def test_preview_text_falls_back_to_description():
    article = {"headline": " ", "description": "— Bo Bichette continued his tear."}
    assert ESPNProvider._preview_text(article) == "Bo Bichette continued his tear."
