"""Tests for backend template validation (3zjp.4 — parity with the editor).

Covers the registry-backed valid-name sets, engine-aligned variable extraction,
the per-string validator (unknown vars + suffix-in-event rules), and the
POST /templates/validate endpoint. Mirrors frontend/src/utils/templateValidation.ts.
"""

from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.templates.validation import (
    build_valid_variable_sets,
    extract_variables,
    valid_condition_names,
    validate_conditional_descriptions,
    validate_fields,
    validate_template,
)

# --- valid-name sets from the live registry ---


def test_valid_sets_include_known_variable_and_suffixes():
    valid_names, base_names = build_valid_variable_sets()
    assert "team_name" in base_names
    assert "team_name" in valid_names
    # An ALL-suffix variable exposes .next/.last variants.
    assert "game_time.next" in valid_names
    assert "game_time.last" in valid_names


# --- extraction mirrors the engine's VARIABLE_PATTERN ---


def test_extract_ignores_literals_and_lowercases():
    # Literals that don't match the engine pattern must not be extracted.
    assert extract_variables("{2024} {1-0} {Team Name} {a.b.c}") == []
    # Real, variable-shaped tokens are extracted and lowercased (engine .lower()).
    assert extract_variables("{TEAM_NAME} {game_recap}") == ["team_name", "game_recap"]
    # @ is a valid name char (vs_@).
    assert extract_variables("{vs_@}") == ["vs_@"]


# --- per-string validation ---


def _sets():
    return build_valid_variable_sets()


def test_known_variable_has_no_warning():
    valid, base = _sets()
    assert validate_template("{team_name}", valid, base, is_event_template=False) == []


def test_unknown_variable_flagged():
    valid, base = _sets()
    warnings = validate_template("{not_a_real_var}", valid, base, is_event_template=False)
    assert len(warnings) == 1
    assert warnings[0].type == "invalid"
    assert "not_a_real_var" in warnings[0].message


def test_literals_never_flagged():
    valid, base = _sets()
    out = validate_template("{2024} at {Stadium Name}!", valid, base, is_event_template=False)
    assert out == []


def test_suffix_not_allowed_in_event_template():
    valid, base = _sets()
    warnings = validate_template("{team_name.next}", valid, base, is_event_template=True)
    assert len(warnings) == 1
    assert warnings[0].type == "suffix_not_allowed"


def test_suffix_allowed_in_team_template():
    valid, base = _sets()
    # team_name is BASE_ONLY, but an ALL-suffix var resolves fine in team templates.
    assert validate_template("{game_time.next}", valid, base, is_event_template=False) == []


def test_validate_fields_returns_only_fields_with_warnings():
    results = validate_fields(
        {"title_format": "{team_name}", "subtitle_template": "{bogus_var}"},
        is_event_template=False,
    )
    assert "title_format" not in results
    assert "subtitle_template" in results


# --- conditions + conditional descriptions ---


def test_valid_condition_names_from_introspection():
    names = valid_condition_names()
    # Representative evaluators that must be present (introspected from _eval_*).
    assert {"always", "is_home", "win_streak", "is_playoff"} <= names
    assert "_eval_is_home" not in names  # prefix stripped


def test_conditional_description_unknown_condition_flagged():
    results = validate_conditional_descriptions(
        [{"condition": "is_hom", "template": "{team_name}"}],  # typo
        is_event_template=False,
    )
    assert "conditional_descriptions[0]" in results
    types = {w.type for w in results["conditional_descriptions[0]"]}
    assert "invalid_condition" in types


def test_conditional_description_bad_template_flagged():
    results = validate_conditional_descriptions(
        [{"condition": "is_home", "template": "{bogus_var}"}],
        is_event_template=False,
    )
    assert "conditional_descriptions[0]" in results
    assert results["conditional_descriptions[0]"][0].type == "invalid"


def test_conditional_description_clean_entry_no_warning():
    results = validate_conditional_descriptions(
        [
            {"condition": "is_home", "template": "{team_name} at home"},
            {"condition": None, "template": "{matchup}"},  # default branch, no condition
        ],
        is_event_template=False,
    )
    assert results == {}


# --- endpoint ---


def test_validate_endpoint_conditional_descriptions():
    client = TestClient(app)
    resp = client.post(
        "/api/v1/templates/validate",
        json={
            "template_type": "team",
            "fields": {},
            "conditional_descriptions": [
                {"condition": "is_bogus", "template": "{team_name}"}
            ],
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert "conditional_descriptions[0]" in body["warnings"]


def test_validate_endpoint_reports_warnings():
    client = TestClient(app)
    resp = client.post(
        "/api/v1/templates/validate",
        json={"template_type": "team", "fields": {"description_template": "{bogus_var}"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is False
    assert "description_template" in body["warnings"]
    assert body["warnings"]["description_template"][0]["type"] == "invalid"


def test_validate_endpoint_clean_template():
    client = TestClient(app)
    resp = client.post(
        "/api/v1/templates/validate",
        json={"template_type": "team", "fields": {"title_format": "{team_name} {sport}"}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["valid"] is True
    assert body["warnings"] == {}
