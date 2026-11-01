"""API tests for the stream-ordering settings endpoint (epic teamarr-5ag.5).

Covers the mode/points fields on StreamOrderingRuleModel: round-trip through
PUT/GET, legacy-safe defaulting when mode is omitted, validation of bad
mode/points, and parity through the combined /settings endpoint.
"""

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.database import get_db, init_db

client = TestClient(app)

STREAM_ORDERING = "/api/v1/settings/stream-ordering"
STREAM_ORDERING_SCOPES = f"{STREAM_ORDERING}/scopes"
MANAGED_TEAM_SCOPE = f"{STREAM_ORDERING}/managed-team-scope"


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()


def test_put_and_get_score_rule_round_trips():
    resp = client.put(
        STREAM_ORDERING,
        json={
            "rules": [
                {"type": "regex", "value": ".*4K.*", "priority": 99, "mode": "score", "points": 25},
            ]
        },
    )
    assert resp.status_code == 200
    rule = client.get(STREAM_ORDERING).json()["rules"][0]
    assert rule["mode"] == "score"
    assert rule["points"] == 25


def test_omitted_mode_defaults_to_priority():
    """A payload without mode (old client / pre-feature import) must stay hard."""
    resp = client.put(
        STREAM_ORDERING,
        json={"rules": [{"type": "m3u", "value": "Acme", "priority": 3}]},
    )
    assert resp.status_code == 200
    rule = client.get(STREAM_ORDERING).json()["rules"][0]
    assert rule["mode"] == "priority"
    assert rule["points"] == 0


def test_negative_points_accepted():
    resp = client.put(
        STREAM_ORDERING,
        json={
            "rules": [
                {"type": "regex", "value": ".*SD.*", "priority": 99, "mode": "score", "points": -50}
            ]
        },
    )
    assert resp.status_code == 200
    assert client.get(STREAM_ORDERING).json()["rules"][0]["points"] == -50


def test_invalid_mode_rejected():
    resp = client.put(
        STREAM_ORDERING,
        json={"rules": [{"type": "m3u", "value": "Acme", "priority": 3, "mode": "bogus"}]},
    )
    assert resp.status_code == 422


def test_points_out_of_range_rejected():
    resp = client.put(
        STREAM_ORDERING,
        json={
            "rules": [
                {
                    "type": "regex",
                    "value": ".*x.*",
                    "priority": 99,
                    "mode": "score",
                    "points": 10_000_000,
                }
            ]
        },
    )
    assert resp.status_code == 422


def test_combined_settings_carries_mode_and_points():
    client.put(
        STREAM_ORDERING,
        json={
            "rules": [
                {"type": "regex", "value": ".*HD.*", "priority": 99, "mode": "score", "points": 10}
            ]
        },
    )
    combined = client.get("/api/v1/settings").json()
    rules = combined["stream_ordering"]["rules"]
    assert rules[0]["mode"] == "score"
    assert rules[0]["points"] == 10


def test_scoped_ruleset_rejects_duplicate_league_assignments():
    payload = {
        "name": "Baseball",
        "sports": ["baseball"],
        "leagues": ["mlb"],
        "rules": [],
        "use_global_scoring": True,
        "use_global_priority": True,
    }
    created = client.post(STREAM_ORDERING_SCOPES, json=payload)
    assert created.status_code == 201
    assert created.json()["leagues"] == ["mlb"]

    duplicate = client.post(
        STREAM_ORDERING_SCOPES,
        json={**payload, "name": "MLB alternate", "sports": [], "leagues": ["mlb"]},
    )
    assert duplicate.status_code == 409


def test_scoped_ruleset_requires_a_sport_or_league():
    response = client.post(
        STREAM_ORDERING_SCOPES,
        json={
            "name": "Empty",
            "sports": [],
            "leagues": [],
            "rules": [],
            "use_global_scoring": True,
            "use_global_priority": True,
        },
    )
    assert response.status_code == 400


def test_managed_team_scope_round_trips_channel_team_selector():
    response = client.put(
        MANAGED_TEAM_SCOPE,
        json={
            "rules": [
                {
                    "type": "not_team_feed",
                    "value": "[channel team]",
                    "priority": 99,
                    "mode": "priority",
                    "points": 0,
                }
            ],
            "use_global_scoring": False,
            "use_global_priority": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Team Channels"
    assert response.json()["rules"][0]["value"] == "[channel team]"
    assert client.get(MANAGED_TEAM_SCOPE).json()["use_global_scoring"] is False


def test_managed_team_scope_is_visible_for_an_enabled_team_without_a_channel_row():
    with get_db() as conn:
        conn.execute(
            "INSERT INTO teams "
            "(provider_team_id, primary_league, sport, team_name, channel_id, "
            "managed_channel_enabled) VALUES ('team-1', 'mlb', 'baseball', 'Team', 'team-1', 1)"
        )

    assert client.get(MANAGED_TEAM_SCOPE).json()["has_managed_channels"] is True


def test_channel_team_selector_is_rejected_for_non_feed_rules():
    response = client.put(
        MANAGED_TEAM_SCOPE,
        json={
            "rules": [
                {
                    "type": "regex",
                    "value": "[channel team]",
                    "priority": 1,
                    "mode": "priority",
                    "points": 0,
                }
            ]
        },
    )
    assert response.status_code == 400


def test_channel_team_selector_is_rejected_outside_the_managed_team_scope():
    response = client.put(
        STREAM_ORDERING,
        json={
            "rules": [
                {
                    "type": "team_feed",
                    "value": "[channel team]",
                    "priority": 1,
                    "mode": "priority",
                    "points": 0,
                }
            ]
        },
    )
    assert response.status_code == 400
