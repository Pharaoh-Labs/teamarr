"""Server-side template preview endpoint + condition trace (#357, #355 items 12/16).

Covers:
1. ConditionalDescriptionSelector.select_with_trace — per-row matched/selected/
   reason semantics, priority ordering, no-event degradation, and that select()
   (the generation path) still returns the same choice.
2. TemplateResolver.resolve_with_map — the real substitution/cleanup core
   against a plain variable map (static-sample preview path).
3. POST /api/v1/templates/preview — static fallback and live-context modes.
"""

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.core.types import Event, EventStatus, Team, Venue
from teamarr.services import league_mappings as lm
from teamarr.templates.conditions import ConditionalDescriptionSelector
from teamarr.templates.context import GameContext, TeamChannelContext, TemplateContext
from teamarr.templates.resolver import TemplateResolver


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


OPTIONS = [
    {"condition": "is_home", "priority": 50, "template": "Home: {team_name}"},
    {"condition": "is_away", "priority": 50, "template": "Away: {team_name}"},
    {"priority": 100, "template": "Default: {team_name} vs {opponent}"},
]


# --- select_with_trace -------------------------------------------------------


class TestSelectWithTrace:
    def test_empty_options(self):
        sel = ConditionalDescriptionSelector()
        template, trace = sel.select_with_trace(None, None, None)
        assert template == ""
        assert trace == []

    def test_no_event_only_default_matches(self):
        """Without event data, conditional rows can't evaluate; default fires."""
        sel = ConditionalDescriptionSelector()
        template, trace = sel.select_with_trace(OPTIONS, None, None)
        assert template == "Default: {team_name} vs {opponent}"
        assert [r["matched"] for r in trace] == [False, False, True]
        assert [r["selected"] for r in trace] == [False, False, True]
        assert "not evaluated" in trace[0]["reason"]
        assert "no event data" in trace[0]["reason"]

    def test_matched_condition_outranks_default(self):
        ctx = _ctx(is_home=True)
        sel = ConditionalDescriptionSelector()
        template, trace = sel.select_with_trace(OPTIONS, ctx, ctx.game_context)
        assert template == "Home: {team_name}"
        assert trace[0]["matched"] and trace[0]["selected"]
        assert "evaluated true" in trace[0]["reason"]
        # is_away evaluated but false
        assert not trace[1]["matched"]
        assert "evaluated false" in trace[1]["reason"]
        # default matched but lost on priority — annotated why
        assert trace[2]["matched"] and not trace[2]["selected"]
        assert "outranked by priority 50" in trace[2]["reason"]

    def test_away_side(self):
        ctx = _ctx(is_home=False)
        sel = ConditionalDescriptionSelector()
        template, trace = sel.select_with_trace(OPTIONS, ctx, ctx.game_context)
        assert template == "Away: {team_name}"
        assert trace[1]["selected"]

    def test_empty_template_row_skipped(self):
        options = [{"condition": "is_home", "priority": 10, "template": ""}] + OPTIONS
        ctx = _ctx(is_home=True)
        sel = ConditionalDescriptionSelector()
        template, trace = sel.select_with_trace(options, ctx, ctx.game_context)
        assert template == "Home: {team_name}"
        assert "empty template" in trace[0]["reason"]
        assert not trace[0]["matched"]

    def test_condition_value_in_reason(self):
        options = [
            {"condition": "win_streak", "condition_value": "5", "priority": 10,
             "template": "Streaking"},
            {"priority": 100, "template": "Default"},
        ]
        ctx = _ctx()
        sel = ConditionalDescriptionSelector()
        _, trace = sel.select_with_trace(options, ctx, ctx.game_context)
        assert "'win_streak' (value: 5) evaluated false" == trace[0]["reason"]

    def test_select_delegates_to_trace(self):
        """The generation-path select() returns the same template."""
        ctx = _ctx(is_home=True)
        sel = ConditionalDescriptionSelector()
        assert sel.select(OPTIONS, ctx, ctx.game_context) == "Home: {team_name}"


# --- resolve_with_map --------------------------------------------------------


class TestResolveWithMap:
    def test_substitution_and_unknown_literal(self):
        r = TemplateResolver()
        out = r.resolve_with_map(
            "{home_team} vs {away_team} {nonsense_var}",
            {"home_team": "Celtics", "away_team": "Pistons"},
        )
        assert out == "Celtics vs Pistons {nonsense_var}"

    def test_cleanup_matches_engine(self):
        """Empty-value artifacts get the same cleanup pass as resolve()."""
        r = TemplateResolver()
        out = r.resolve_with_map(
            "{home_team} ({home_rank})  final",
            {"home_team": "Celtics", "home_rank": ""},
        )
        assert out == "Celtics final"

    def test_leading_the_capitalized(self):
        r = TemplateResolver()
        out = r.resolve_with_map("{team_name_the} play", {"team_name_the": "the Celtics"})
        assert out == "The Celtics play"

    def test_empty_template(self):
        assert TemplateResolver().resolve_with_map("", {"x": "y"}) == ""


# --- POST /templates/preview -------------------------------------------------


client = TestClient(app)


class TestPreviewEndpoint:
    def test_static_render(self):
        """No league/live → static sample data through the real resolver."""
        resp = client.post(
            "/api/v1/templates/preview",
            json={
                "live": False,
                "fields": {"subtitle": "{away_team} at {home_team}",
                           "typo": "{not_a_var}"},
                "conditional_descriptions": OPTIONS,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["live"] is False
        assert data["fields"]["subtitle"]  # rendered, non-empty
        assert "{away_team}" not in data["fields"]["subtitle"]
        assert data["fields"]["typo"] == "{not_a_var}"  # unknown stays literal
        # No event → default row fires, trace explains the conditionals
        cond = data["conditional"]
        assert cond["selected_index"] == 2
        assert cond["rendered"].startswith("Default:")
        assert "no event data" in cond["rows"][0]["reason"]

    def test_live_render_uses_real_context(self, monkeypatch):
        """With a live context, fields and conditions resolve from the event."""
        from teamarr.api.routes import templates as t

        monkeypatch.setattr(t, "build_live_context", lambda league: _ctx(is_home=True))
        resp = client.post(
            "/api/v1/templates/preview",
            json={
                "league": "nba",
                "live": True,
                "fields": {"subtitle": "{away_team} at {home_team}"},
                "conditional_descriptions": OPTIONS,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["live"] is True
        assert data["fields"]["subtitle"] == "Detroit Pistons at Boston Celtics"
        cond = data["conditional"]
        assert cond["selected_index"] == 0
        assert cond["rendered"] == "Home: Boston Celtics"
        assert cond["rows"][2]["matched"] is True  # default matched but outranked
        assert cond["rows"][2]["selected"] is False

    def test_live_falls_back_to_static(self, monkeypatch):
        """Provider failure (no context) degrades to static samples, live=false."""
        from teamarr.api.routes import templates as t
        from teamarr.templates import preview as p

        monkeypatch.setattr(t, "build_live_context", lambda league: None)
        monkeypatch.setattr(p, "lookup_league_fields", lambda code: ("basketball", "espn"))
        resp = client.post(
            "/api/v1/templates/preview",
            json={
                "league": "nba",
                "live": True,
                "fields": {"subtitle": "{away_team} at {home_team}"},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["live"] is False
        assert data["fields"]["subtitle"]
        assert "{away_team}" not in data["fields"]["subtitle"]
        assert data["conditional"] is None  # none requested
