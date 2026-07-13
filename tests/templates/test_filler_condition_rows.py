"""Filler condition rows (#420, cajd.3).

Covers the generator read path for per-register condition rows: reference-game
selection (pregame → next, postgame/idle → last), refreshed finality,
per-field highest-priority-match-wins with fall-to-base, the multi-level
description cascade-on-empty, the offseason register staying separate, and
the legacy final/not-final conversion shim at config-build time.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from teamarr.consumers.filler.event_filler import EventFillerGenerator
from teamarr.consumers.filler.generator import FillerGenerator
from teamarr.core.filler_types import (
    FillerConfig,
    FillerTemplate,
    FillerType,
    OffseasonFillerTemplate,
    legacy_conditional_to_rows,
)
from teamarr.core.types import Event, EventStatus, Team
from teamarr.templates.conditions import get_condition_selector
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext


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


def _event(state: str = "post", **kw) -> Event:
    base = dict(
        id="1",
        provider="espn",
        name="A vs B",
        short_name="A @ B",
        start_time=datetime(2026, 6, 17, 19, 0, tzinfo=UTC),
        league="nba",
        sport="basketball",
        status=EventStatus(state=state),
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


def _filler_context(
    next_event: Event | None = None, last_event: Event | None = None
) -> TemplateContext:
    tc = TeamChannelContext(team_id="1", league="nba", sport="basketball", team_name="Home Heat")
    return TemplateContext(
        game_context=None,
        team_config=tc,
        team_stats=None,
        next_game=GameContext(event=next_event) if next_event else None,
        last_game=GameContext(event=last_event) if last_event else None,
    )


def _generator(refreshed_event: Event | None = None) -> FillerGenerator:
    service = MagicMock()
    if refreshed_event is not None:
        service.refresh_event_status.return_value = refreshed_event
    else:
        service.refresh_event_status.side_effect = lambda e: e
    return FillerGenerator(service)


BASE = FillerTemplate(title="Base Title", subtitle="Base Sub", description="Base description")


# --- legacy conversion shim ---


def test_legacy_conversion_disabled_or_empty_yields_no_rows():
    assert legacy_conditional_to_rows(None) == []
    assert legacy_conditional_to_rows({}) == []
    assert legacy_conditional_to_rows({"enabled": False, "description_final": "x"}) == []
    assert legacy_conditional_to_rows({"enabled": True}) == []


def test_legacy_conversion_builds_disjoint_rows():
    rows = legacy_conditional_to_rows(
        {
            "enabled": True,
            "title_final": "Final Title",
            "description_final": "{game_recap}",
            "description_not_final": "Not over yet.",
            "subtitle_not_final": "",  # falsy = unset, matching the old `or` chain
        }
    )
    assert [r["condition"] for r in rows] == ["is_final", "is_not_final"]
    final, not_final = rows
    assert final["title"] == "Final Title"
    assert final["template"] == "{game_recap}"
    assert "subtitle" not in not_final
    assert not_final["template"] == "Not over yet."


# --- selector: per-field winners + runner-up descriptions ---


def test_select_filler_fields_returns_runner_up_descriptions():
    ctx = _filler_context(last_event=_event("post"))
    rows = [
        {"condition": "is_final", "priority": 20, "template": "primary"},
        {"condition": "is_final", "priority": 40, "template": "second"},
        {"condition": "is_not_final", "priority": 10, "template": "never matches"},
        {"priority": 100, "template": "default row"},
    ]
    fields, runners_up = get_condition_selector().select_filler_fields(
        rows, ctx, ctx.last_game
    )
    assert fields["description"] == "primary"
    assert runners_up == ["second", "default row"]


# --- team generator: reference game per register ---


def test_pregame_rows_evaluate_against_next_game():
    gen = _generator()
    config = FillerConfig(
        pregame_template=BASE,
        pregame_rows=[
            {"condition": "has_preview", "priority": 10, "template": "{game_preview}"}
        ],
    )
    ctx = _filler_context(next_event=_event("pre", game_preview="Aces vs. Heat preview"))
    selected = gen._select_register_template(FillerType.PREGAME, config, ctx)
    assert selected.description == "{game_preview}"
    # Pregame does not refresh — its reference is the upcoming game.
    gen._service.refresh_event_status.assert_not_called()

    # No preview → row doesn't match → base register untouched.
    ctx = _filler_context(next_event=_event("pre"))
    assert gen._select_register_template(FillerType.PREGAME, config, ctx) is config.pregame_template


def test_postgame_finality_uses_refreshed_status():
    # Cached event says in-progress; the provider refresh says final.
    gen = _generator(refreshed_event=_event("post"))
    config = FillerConfig(
        postgame_template=BASE,
        postgame_rows=[
            {"condition": "is_final", "priority": 50, "template": "final text"},
            {"condition": "is_not_final", "priority": 50, "template": "live text"},
        ],
    )
    ctx = _filler_context(last_event=_event("in"))
    selected = gen._select_register_template(FillerType.POSTGAME, config, ctx)
    assert selected.description == "final text"
    gen._service.refresh_event_status.assert_called_once()


def test_per_field_falls_to_base_when_row_does_not_set_it():
    gen = _generator()
    config = FillerConfig(
        idle_template=BASE,
        idle_rows=[{"condition": "is_final", "priority": 50, "template": "rows description"}],
    )
    ctx = _filler_context(last_event=_event("post"))
    selected = gen._select_register_template(FillerType.IDLE, config, ctx)
    assert selected.description == "rows description"
    assert selected.title == "Base Title"
    assert selected.subtitle == "Base Sub"
    assert selected.description_fallbacks == ["Base description"]


def test_no_reference_game_leaves_conditioned_rows_unmatched():
    gen = _generator()
    config = FillerConfig(
        idle_template=BASE,
        idle_rows=[{"condition": "is_final", "priority": 50, "template": "rows description"}],
    )
    selected = gen._select_register_template(FillerType.IDLE, config, _filler_context())
    assert selected is config.idle_template


def test_offseason_register_ignores_rows():
    gen = _generator()
    config = FillerConfig(
        idle_template=BASE,
        idle_offseason=OffseasonFillerTemplate(enabled=True, description="Offseason text"),
        idle_rows=[{"priority": 100, "template": "default row"}],
    )
    ctx = _filler_context(last_event=_event("post"))
    selected = gen._select_register_template(FillerType.IDLE, config, ctx, is_offseason=True)
    assert selected.description == "Offseason text"


# --- config conversion: rows plumbed, legacy shim only when rows empty ---


def test_template_to_filler_config_prefers_rows_over_legacy():
    from teamarr.database.templates import Template, template_to_filler_config

    template = Template(
        id=1,
        name="t",
        template_type="team",
        postgame_conditional={"enabled": True, "description_final": "legacy final"},
        postgame_conditional_rows=[{"condition": "always", "priority": 50, "template": "rows"}],
        idle_conditional={"enabled": True, "description_final": "legacy idle"},
        pregame_conditional_rows=[{"condition": "has_preview", "priority": 10, "template": "p"}],
    )
    config = template_to_filler_config(template)
    # Rows column wins when non-empty; legacy converts only as fallback.
    assert config.postgame_rows == [{"condition": "always", "priority": 50, "template": "rows"}]
    assert [r["template"] for r in config.idle_rows] == ["legacy idle"]
    assert config.idle_rows[0]["condition"] == "is_final"
    assert config.pregame_rows[0]["condition"] == "has_preview"


# --- multi-level description cascade at render time ---


def test_description_cascade_walks_runner_ups_then_base():
    gen = EventFillerGenerator(service=None)
    event = _event("post")  # final, no recap published
    tc = TeamChannelContext(team_id="1", league="nba", sport="basketball", team_name="Home Heat")
    ctx = TemplateContext(game_context=GameContext(event=event), team_config=tc, team_stats=None)

    template = FillerTemplate(
        title="Postgame",
        description="{game_recap}",  # resolves empty
        description_fallbacks=["{game_event_note}", "constructed text"],  # first also empty
    )
    programmes = gen._generate_filler(
        start_dt=datetime(2026, 6, 17, 22, 0, tzinfo=UTC),
        end_dt=datetime(2026, 6, 18, 2, 0, tzinfo=UTC),
        template=template,
        context=ctx,
        channel_id="ch1",
        config=MagicMock(xmltv_categories=[]),
        logo_url=None,
        filler_type="postgame",
        event=event,
    )
    assert programmes
    assert all(p.description == "constructed text" for p in programmes)
