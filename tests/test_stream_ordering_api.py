"""API tests for the stream-ordering settings endpoint (epic teamarr-5ag.5).

Covers the mode/points fields on StreamOrderingRuleModel: round-trip through
PUT/GET, legacy-safe defaulting when mode is omitted, validation of bad
mode/points, and parity through the combined /settings endpoint.
"""

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.database import init_db

client = TestClient(app)

STREAM_ORDERING = "/api/v1/settings/stream-ordering"


@pytest.fixture(autouse=True)
def _isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()


def test_put_and_get_score_rule_round_trips():
    resp = client.put(
        STREAM_ORDERING,
        json={
            "rules": [
                {"type": "regex", "value": ".*4K.*", "priority": 99,
                 "mode": "score", "points": 25},
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
        json={"rules": [{"type": "regex", "value": ".*SD.*", "priority": 99,
                         "mode": "score", "points": -50}]},
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
        json={"rules": [{"type": "regex", "value": ".*x.*", "priority": 99,
                         "mode": "score", "points": 10_000_000}]},
    )
    assert resp.status_code == 422


def test_combined_settings_carries_mode_and_points():
    client.put(
        STREAM_ORDERING,
        json={"rules": [{"type": "regex", "value": ".*HD.*", "priority": 99,
                         "mode": "score", "points": 10}]},
    )
    combined = client.get("/api/v1/settings").json()
    rules = combined["stream_ordering"]["rules"]
    assert rules[0]["mode"] == "score"
    assert rules[0]["points"] == 10
