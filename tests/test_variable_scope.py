"""Tests for template-type scoping on template variables.

Verifies that:
1. VariableDefinition carries a TemplateScope (defaults to ALL).
2. VariableRegistry.filter_by_template_type returns the right subset.
3. GET /variables endpoint honors the ?template_type= query param.
4. Representative team-only variables are excluded from event templates.
5. Representative event-only (feed_team*) variables are excluded from team templates.
6. Fail-open: unknown/None template_type returns the full registry.
"""

from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.templates.variables import (
    TemplateScope,
    VariableDefinition,
    get_registry,
)

# --- Registry-level tests ---


def test_variable_definition_default_scope_is_all():
    def extractor(ctx, gctx):
        return ""

    # Minimal construction — defaults exercised
    from teamarr.templates.variables.registry import (
        Category,
        SuffixRules,
    )

    v = VariableDefinition(
        name="dummy",
        category=Category.IDENTITY,
        suffix_rules=SuffixRules.ALL,
        extractor=extractor,
    )
    assert v.scope is TemplateScope.ALL


def test_filter_by_template_type_team_excludes_event_only():
    registry = get_registry()
    team_scoped = registry.filter_by_template_type("team")
    team_names = {v.name for v in team_scoped}

    # No EVENT_ONLY variable should appear
    event_only_names = {
        v.name for v in registry.all_variables() if v.scope is TemplateScope.EVENT_ONLY
    }
    assert event_only_names, "expected at least one EVENT_ONLY variable in the registry"
    assert not (event_only_names & team_names)


def test_filter_by_template_type_event_excludes_team_only():
    registry = get_registry()
    event_scoped = registry.filter_by_template_type("event")
    event_names = {v.name for v in event_scoped}

    team_only_names = {
        v.name for v in registry.all_variables() if v.scope is TemplateScope.TEAM_ONLY
    }
    assert team_only_names, "expected at least one TEAM_ONLY variable in the registry"
    assert not (team_only_names & event_names)


def test_filter_by_template_type_none_returns_all():
    registry = get_registry()
    unscoped = registry.filter_by_template_type(None)
    assert len(unscoped) == registry.count()


def test_filter_by_template_type_unknown_returns_all():
    registry = get_registry()
    # Fail-open behavior: unknown values do not filter
    unscoped = registry.filter_by_template_type("garbage")
    assert len(unscoped) == registry.count()


def test_scope_counts_partition_the_registry():
    registry = get_registry()
    total = registry.count()
    team_count = len(registry.filter_by_template_type("team"))
    event_count = len(registry.filter_by_template_type("event"))

    # Each scope view = ALL count + that-scope-only count.
    # So team_count + event_count = 2*ALL + TEAM_ONLY + EVENT_ONLY
    # And 2*ALL + TEAM_ONLY + EVENT_ONLY = ALL + total
    all_count = sum(1 for v in registry.all_variables() if v.scope is TemplateScope.ALL)
    assert team_count + event_count == all_count + total


# --- API endpoint tests ---


def _client():
    return TestClient(app)


def test_variables_endpoint_no_filter_returns_all():
    r = _client().get("/api/v1/variables")
    assert r.status_code == 200
    data = r.json()
    assert data["template_type"] is None
    assert data["total"] == get_registry().count()


def test_variables_endpoint_team_excludes_feed_team_family():
    r = _client().get("/api/v1/variables?template_type=team")
    assert r.status_code == 200
    data = r.json()
    assert data["template_type"] == "team"
    names = _flatten_names(data["categories"])
    # feed_team family should be absent
    for hidden in (
        "feed_team",
        "feed_team_short",
        "feed_team_abbrev",
        "feed_team_abbrev_lower",
        "feed_team_logo",
        "is_home_feed",
        "is_away_feed",
        "feed_home_away",
    ):
        assert hidden not in names, f"{hidden} should not appear in team picker"


def test_variables_endpoint_event_excludes_team_perspective():
    r = _client().get("/api/v1/variables?template_type=event")
    assert r.status_code == 200
    data = r.json()
    assert data["template_type"] == "event"
    names = _flatten_names(data["categories"])
    # Representative team-perspective variables should be absent
    for hidden in (
        "team_name",
        "team_abbrev",
        "opponent",
        "opponent_abbrev",
        "is_home",
        "is_away",
        "vs_at",
        "vs_@",
        "team_record",
        "opponent_record",
        "win_streak",
        "team_score",
        "opponent_score",
        "result",
        "result_text",
        "team_rank",
        "is_ranked",
        "is_ranked_matchup",
        "playoff_seed",
        "games_back",
        "pro_division",
        "college_conference",
        "odds_moneyline",
        "odds_opponent_moneyline",
    ):
        assert hidden not in names, f"{hidden} should not appear in event picker"


def test_variables_endpoint_positional_available_in_both():
    """Positional (home/away) and game-level variables must appear in both scopes."""
    team_names = _flatten_names(
        _client().get("/api/v1/variables?template_type=team").json()["categories"]
    )
    event_names = _flatten_names(
        _client().get("/api/v1/variables?template_type=event").json()["categories"]
    )
    must_appear_in_both = (
        "home_team",
        "away_team",
        "home_team_score",
        "away_team_score",
        "home_team_record",
        "away_team_record",
        "venue",
        "venue_city",
        "game_date",
        "game_time",
        "matchup",
        "league",
        "sport",
        "season_type",
        "is_playoff",
        "is_preseason",
        "odds_spread",
        "broadcast_simple",
        "overtime_text",
        "overtime_short",
        "final_score",
    )
    for name in must_appear_in_both:
        assert name in team_names, f"{name} must appear in team picker"
        assert name in event_names, f"{name} must appear in event picker"


def test_variables_endpoint_feed_team_available_on_event():
    """Feed-team variables must appear only in the event scope."""
    event_names = _flatten_names(
        _client().get("/api/v1/variables?template_type=event").json()["categories"]
    )
    for required in ("feed_team", "feed_team_short", "is_home_feed", "feed_home_away"):
        assert required in event_names


# --- Helpers ---


def _flatten_names(categories: list[dict]) -> set[str]:
    """Collect every variable name across every returned category."""
    names: set[str] = set()
    for cat in categories:
        for v in cat.get("variables", []):
            names.add(v["name"])
    return names
