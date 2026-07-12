"""Conditional title/subtitle rows (#370 part 2).

Rows in ``conditional_descriptions`` may carry optional ``title``/``subtitle``
overrides. Selection runs PER FIELD: for each of title/subtitle/description,
the highest-priority matching row that DEFINES that field wins; omitted
fields fall through. Ties at the winning priority stay random for
descriptions (variety feature) but are deterministic (first in input order)
for titles and subtitles.

Covers the selector (select_fields_with_trace), the preview endpoint's
per-field conditional blocks, and validation of the new row fields.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.core.types import Event, EventStatus, Team, Venue
from teamarr.services import league_mappings as lm
from teamarr.templates.conditions import ConditionalDescriptionSelector
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.validation import validate_conditional_descriptions


@pytest.fixture(autouse=True)
def real_league_service(db_factory):
    """Real LeagueMappingService over the seeded temp DB (extractors need it)."""
    prior = lm._league_mapping_service
    lm.init_league_mapping_service(db_factory)
    yield
    lm._league_mapping_service = prior


def _team(name, abbrev, id_="1"):
    return Team(
        id=id_, provider="espn", name=name, short_name=name,
        abbreviation=abbrev, league="nba", sport="basketball",
    )


def _ctx(is_home=True):
    home = _team("Boston Celtics", "BOS", "1")
    away = _team("Detroit Pistons", "DET", "2")
    event = Event(
        id="e1", provider="espn", name="Detroit Pistons at Boston Celtics",
        short_name="DET @ BOS",
        start_time=datetime(2026, 7, 10, 19, 0, tzinfo=UTC),
        home_team=home, away_team=away, status=EventStatus(state="pre"),
        league="nba", sport="basketball",
        venue=Venue(name="TD Garden", city="Boston", state="MA"),
    )
    team = home if is_home else away
    game_ctx = GameContext(event=event, is_home=is_home)
    return TemplateContext(
        game_context=game_ctx,
        team_config=TeamChannelContext(
            team_id=team.id, league="nba", sport="basketball",
            team_name=team.name, team_abbrev=team.abbreviation,
        ),
        team_stats=None,
    )


# ---------------------------------------------------------------------------
# select_fields_with_trace
# ---------------------------------------------------------------------------


class TestPerFieldSelection:
    def test_row_overrides_all_three_fields(self):
        sel = ConditionalDescriptionSelector()
        ctx = _ctx(is_home=True)
        options = [
            {"condition": "is_home", "priority": 40,
             "title": "T: {team_name}", "subtitle": "S: {opponent}",
             "template": "D: home game"},
            {"priority": 100, "template": "Default desc"},
        ]
        fields, trace = sel.select_fields_with_trace(options, ctx, ctx.game_context)
        assert fields == {
            "title": "T: {team_name}",
            "subtitle": "S: {opponent}",
            "description": "D: home game",
        }
        assert trace[0]["selected_for"] == ["description", "title", "subtitle"]
        assert trace[0]["selected"] is True

    def test_fields_fall_through_independently(self):
        """A title-only winner leaves description to a lower-priority row."""
        sel = ConditionalDescriptionSelector()
        ctx = _ctx(is_home=True)
        options = [
            {"condition": "is_home", "priority": 10, "title": "Big Game!", "template": ""},
            {"condition": "is_home", "priority": 50, "template": "Home description"},
        ]
        fields, trace = sel.select_fields_with_trace(options, ctx, ctx.game_context)
        assert fields == {"title": "Big Game!", "description": "Home description"}
        assert "subtitle" not in fields
        assert trace[0]["selected_for"] == ["title"]
        assert trace[0]["selected"] is False  # not the description winner
        assert trace[1]["selected_for"] == ["description"]
        assert trace[1]["selected"] is True

    def test_title_only_row_is_evaluated_despite_empty_template(self):
        sel = ConditionalDescriptionSelector()
        ctx = _ctx(is_home=True)
        options = [{"condition": "is_home", "priority": 40, "title": "Only title"}]
        fields, trace = sel.select_fields_with_trace(options, ctx, ctx.game_context)
        assert fields == {"title": "Only title"}
        assert trace[0]["matched"] is True
        assert "evaluated true" in trace[0]["reason"]

    def test_row_with_no_content_is_skipped(self):
        sel = ConditionalDescriptionSelector()
        ctx = _ctx(is_home=True)
        options = [{"condition": "is_home", "priority": 40, "template": ""}]
        fields, trace = sel.select_fields_with_trace(options, ctx, ctx.game_context)
        assert fields == {}
        assert "empty template" in trace[0]["reason"]

    def test_title_ties_are_deterministic_first_in_input_order(self):
        sel = ConditionalDescriptionSelector()
        ctx = _ctx(is_home=True)
        options = [
            {"condition": "is_home", "priority": 40, "title": "First title"},
            {"condition": "is_home", "priority": 40, "title": "Second title"},
        ]
        # Deterministic: same winner every run.
        for _ in range(20):
            fields, _ = sel.select_fields_with_trace(options, ctx, ctx.game_context)
            assert fields["title"] == "First title"

    def test_description_ties_stay_random_among_candidates(self):
        sel = ConditionalDescriptionSelector()
        ctx = _ctx(is_home=True)
        options = [
            {"condition": "is_home", "priority": 40, "template": "Desc A"},
            {"condition": "is_home", "priority": 40, "template": "Desc B"},
        ]
        seen = set()
        for _ in range(50):
            fields, _ = sel.select_fields_with_trace(options, ctx, ctx.game_context)
            seen.add(fields["description"])
        assert seen <= {"Desc A", "Desc B"}
        assert len(seen) == 2  # both candidates appear across runs

    def test_non_matching_condition_contributes_nothing(self):
        sel = ConditionalDescriptionSelector()
        ctx = _ctx(is_home=True)
        options = [
            {"condition": "is_away", "priority": 10, "title": "Away title", "template": "x"},
            {"priority": 100, "template": "Default desc"},
        ]
        fields, _ = sel.select_fields_with_trace(options, ctx, ctx.game_context)
        assert "title" not in fields
        assert fields["description"] == "Default desc"

    def test_default_row_can_carry_title(self):
        sel = ConditionalDescriptionSelector()
        ctx = _ctx(is_home=True)
        options = [{"priority": 100, "title": "Always title", "template": "Default"}]
        fields, _ = sel.select_fields_with_trace(options, ctx, ctx.game_context)
        assert fields == {"title": "Always title", "description": "Default"}

    def test_select_with_trace_wrapper_unchanged_for_descriptions(self):
        sel = ConditionalDescriptionSelector()
        ctx = _ctx(is_home=True)
        options = [
            {"condition": "is_home", "priority": 50, "template": "Home: {team_name}"},
            {"priority": 100, "template": "Default"},
        ]
        template, trace = sel.select_with_trace(options, ctx, ctx.game_context)
        assert template == "Home: {team_name}"
        assert trace[0]["selected"] is True


# ---------------------------------------------------------------------------
# POST /templates/preview — per-field conditional blocks
# ---------------------------------------------------------------------------


class TestPreviewEndpoint:
    def test_preview_reports_title_and_subtitle_winners(self):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/templates/preview",
            json={
                "league": "nba",
                "live": False,
                "template_type": "team",
                "fields": {},
                "conditional_descriptions": [
                    {"priority": 100, "title": "Conditional Title",
                     "subtitle": "Conditional Sub", "template": "Conditional Desc"},
                ],
            },
        )
        assert resp.status_code == 200
        cond = resp.json()["conditional"]
        assert cond["rendered"] == "Conditional Desc"
        assert cond["rendered_title"] == "Conditional Title"
        assert cond["rendered_subtitle"] == "Conditional Sub"
        assert cond["selected_index"] == 0
        assert cond["selected_title_index"] == 0
        assert cond["selected_subtitle_index"] == 0
        assert cond["rows"][0]["selected_for"] == ["description", "title", "subtitle"]

    def test_preview_title_fields_none_when_not_defined(self):
        client = TestClient(app)
        resp = client.post(
            "/api/v1/templates/preview",
            json={
                "league": "nba",
                "live": False,
                "template_type": "team",
                "fields": {},
                "conditional_descriptions": [
                    {"priority": 100, "template": "Desc only"},
                ],
            },
        )
        assert resp.status_code == 200
        cond = resp.json()["conditional"]
        assert cond["rendered"] == "Desc only"
        assert cond["rendered_title"] is None
        assert cond["selected_title_index"] is None
        assert cond["rendered_subtitle"] is None
        assert cond["selected_subtitle_index"] is None


# ---------------------------------------------------------------------------
# Validation of row title/subtitle strings
# ---------------------------------------------------------------------------


class TestRowFieldValidation:
    def test_bad_variable_in_title_is_flagged_under_field_key(self):
        results = validate_conditional_descriptions(
            [{"condition": "is_home", "title": "{not_a_real_var}", "template": "ok"}],
            is_event_template=False,
        )
        assert "conditional_descriptions[0].title" in results

    def test_clean_title_and_subtitle_produce_no_warnings(self):
        results = validate_conditional_descriptions(
            [{"condition": "is_home", "title": "{team_name}",
              "subtitle": "{opponent}", "template": "{team_name} hosts"}],
            is_event_template=False,
        )
        assert results == {}
