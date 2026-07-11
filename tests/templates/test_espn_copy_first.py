"""ESPN-copy-first description chains (tvnk.14, #329).

Covers the has_recap/has_preview condition evaluators, the filler
description fallthrough (a provider-copy primary like {game_recap} that
resolves empty falls through to the constructed fallback), and the starter
set's wiring of both.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from teamarr.consumers.filler.event_filler import (
    EventFillerConfig,
    EventFillerGenerator,
    template_to_event_filler_config,
)
from teamarr.core.filler_types import ConditionalFillerTemplate, FillerTemplate
from teamarr.core.types import Event, EventStatus, Team
from teamarr.database.default_templates import DEFAULT_TEMPLATE_SET
from teamarr.templates.conditions import ConditionEvaluator, get_condition_selector
from teamarr.templates.context import (
    GameContext,
    TeamChannelContext,
    TemplateContext,
)


@pytest.fixture(autouse=True)
def mock_league_mapping_service():
    """Mock the league mapping service singleton (full resolution needs it)."""
    svc = MagicMock()
    svc.get_league_alias.side_effect = lambda code: code.upper()
    svc.get_league_display_name.side_effect = lambda code: code.upper()
    svc.get_league_id.side_effect = lambda code: code
    svc.get_league_logo.return_value = ""
    svc.get_gracenote_category.side_effect = lambda code: code.upper()
    svc.get_sport_display_name.side_effect = lambda code: code.title()
    with patch("teamarr.services.league_mappings._league_mapping_service", svc):
        yield svc


def _event(**kw) -> Event:
    base = dict(
        id="1",
        provider="espn",
        name="A vs B",
        short_name="A @ B",
        start_time=datetime(2026, 6, 17, 19, 0, tzinfo=UTC),
        league="nba",
        sport="basketball",
        status=EventStatus(state="post"),
        home_team=Team(
            id="1",
            provider="espn",
            name="Home Heat",
            short_name="Heat",
            abbreviation="HH",
            league="nba",
            sport="basketball",
        ),
        away_team=Team(
            id="2",
            provider="espn",
            name="Away Aces",
            short_name="Aces",
            abbreviation="AA",
            league="nba",
            sport="basketball",
        ),
    )
    base.update(kw)
    return Event(**base)


def _ctx(event: Event) -> tuple[TemplateContext, GameContext]:
    gc = GameContext(event=event)
    tc = TeamChannelContext(team_id="1", league="nba", sport="basketball", team_name="Home Heat")
    return TemplateContext(game_context=gc, team_config=tc, team_stats=None), gc


# --- condition evaluators ---


def test_has_recap_condition():
    ev = ConditionEvaluator()
    ctx, gc = _ctx(_event(game_recap="Heat top Aces for the title"))
    assert ev.evaluate("has_recap", None, ctx, gc) is True

    ctx, gc = _ctx(_event())
    assert ev.evaluate("has_recap", None, ctx, gc) is False


def test_has_preview_condition():
    ev = ConditionEvaluator()
    ctx, gc = _ctx(_event(game_preview="Aces (35-38) vs. Heat…"))
    assert ev.evaluate("has_preview", None, ctx, gc) is True

    ctx, gc = _ctx(_event())
    assert ev.evaluate("has_preview", None, ctx, gc) is False


def test_has_event_note_condition():
    ev = ConditionEvaluator()
    ctx, gc = _ctx(_event(game_event_note="NBA Finals - Game 5"))
    assert ev.evaluate("has_event_note", None, ctx, gc) is True

    ctx, gc = _ctx(_event())
    assert ev.evaluate("has_event_note", None, ctx, gc) is False


def test_has_match_note_condition():
    ev = ConditionEvaluator()
    ctx, gc = _ctx(_event(soccer_match_note="FIFA World Cup, Group C"))
    assert ev.evaluate("has_match_note", None, ctx, gc) is True

    ctx, gc = _ctx(_event())
    assert ev.evaluate("has_match_note", None, ctx, gc) is False


def test_selector_prefers_preview_row_then_constructed_default():
    options = [
        {"condition": "has_preview", "priority": 10, "template": "{game_preview}"},
        {"priority": 100, "template": "constructed", "label": "Default"},
    ]
    selector = get_condition_selector()

    ctx, gc = _ctx(_event(game_preview="Aces (35-38) vs. Heat…"))
    assert selector.select(options, ctx, gc) == "{game_preview}"

    ctx, gc = _ctx(_event())
    assert selector.select(options, ctx, gc) == "constructed"


# --- filler description fallthrough ---


def _postgame_config() -> EventFillerConfig:
    return EventFillerConfig(
        postgame_template=FillerTemplate(
            title="Postgame",
            description="The {team_name} {result_text} the {opponent} {final_score}",
        ),
        postgame_conditional=ConditionalFillerTemplate(
            enabled=True,
            description_final="{game_recap}",
            description_not_final="Not over yet.",
        ),
    )


def test_postgame_conditional_carries_fallback_description():
    gen = EventFillerGenerator(service=None)
    config = _postgame_config()
    selected = gen._select_postgame_template(_event(), config)
    assert selected.description == "{game_recap}"
    assert selected.description_fallback == config.postgame_template.description


def test_filler_render_uses_recap_when_present():
    gen = EventFillerGenerator(service=None)
    event = _event(game_recap="Heat top Aces for the title")
    ctx, _ = _ctx(event)
    template = gen._select_postgame_template(event, _postgame_config())
    programmes = gen._generate_filler(
        start_dt=datetime(2026, 6, 17, 22, 0, tzinfo=UTC),
        end_dt=datetime(2026, 6, 18, 2, 0, tzinfo=UTC),
        template=template,
        context=ctx,
        channel_id="ch1",
        config=EventFillerConfig(),
        logo_url=None,
        filler_type="postgame",
        event=event,
    )
    assert programmes
    assert all(p.description == "Heat top Aces for the title" for p in programmes)


def test_filler_render_falls_through_to_constructed_when_no_recap():
    gen = EventFillerGenerator(service=None)
    event = _event()  # final, but no recap published
    ctx, _ = _ctx(event)
    template = gen._select_postgame_template(event, _postgame_config())
    programmes = gen._generate_filler(
        start_dt=datetime(2026, 6, 17, 22, 0, tzinfo=UTC),
        end_dt=datetime(2026, 6, 18, 2, 0, tzinfo=UTC),
        template=template,
        context=ctx,
        channel_id="ch1",
        config=EventFillerConfig(),
        logo_url=None,
        filler_type="postgame",
        event=event,
    )
    assert programmes
    for p in programmes:
        assert "{game_recap}" not in p.description
        assert "Home Heat" in p.description  # constructed result line rendered


def test_event_config_conversion_passes_pregame_fallback():
    class T:
        pregame_fallback = {
            "title": "Coming up",
            "description": "{game_preview}",
            "description_fallback": "constructed pregame",
        }
        postgame_fallback = None
        postgame_conditional = None
        pregame_enabled = True
        postgame_enabled = True
        xmltv_filler_categories = []

    config = template_to_event_filler_config(T())
    assert config.pregame_template.description == "{game_preview}"
    assert config.pregame_template.description_fallback == "constructed pregame"


# --- starter set wiring ---


def test_starter_set_is_espn_copy_first():
    for spec in DEFAULT_TEMPLATE_SET:
        # Main chain: a has_preview row above the constructed default.
        conds = spec["conditional_descriptions"]
        assert conds[0]["condition"] == "has_preview", spec["name"]
        assert conds[0]["template"].startswith("{game_preview"), spec["name"]
        assert conds[-1]["priority"] == 100, spec["name"]
        assert conds[0]["priority"] < 100, spec["name"]

        # Pregame: preview primary with a constructed fallback.
        pregame = spec["pregame_fallback"]
        assert pregame["description"].startswith("{game_preview"), spec["name"]
        assert pregame["description_fallback"], spec["name"]
        assert "{game_preview" not in pregame["description_fallback"], spec["name"]

        # Postgame: provider-copy primary in the conditional ({game_recap},
        # or tennis's prose-shaped {tennis_result}); constructed fallback.
        cond = spec["postgame_conditional"]
        assert cond["enabled"] is True, spec["name"]
        assert cond["description_final"].startswith(("{game_recap", "{tennis_result")), spec[
            "name"
        ]
        fallback = spec["postgame_fallback"]["description"]
        assert fallback, spec["name"]
        assert "{game_recap" not in fallback, spec["name"]
        assert "{tennis_result" not in fallback, spec["name"]
