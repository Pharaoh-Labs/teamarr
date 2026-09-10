"""Bulk edit covers stream filters, custom regex and the subscription override (#551).

The DB layer always accepted every field; the bulk request model exposed only a
handful. Bulk carries one control per regex: setting a pattern also switches
it on for every selected source, clearing it switches it off. Fields the
request does not mention are left exactly as they were.
"""

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.database import init_db

client = TestClient(app)


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()


def _make_group(name: str, **extra) -> int:
    resp = client.post("/api/v1/groups", json={"name": name, "leagues": ["eng.1"], **extra})
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _get(gid: int) -> dict:
    return client.get(f"/api/v1/groups/{gid}").json()


class TestBulkRegex:
    def test_setting_a_pattern_also_enables_it_on_every_group(self, isolated_db):
        a, b = _make_group("A"), _make_group("B")

        resp = client.put(
            "/api/v1/groups/bulk",
            json={
                "group_ids": [a, b],
                "stream_include_regex": r"EPL|Premier",
                "custom_regex_teams": r"(?P<team1>\w+) v (?P<team2>\w+)",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["total_updated"] == 2

        for gid in (a, b):
            got = _get(gid)
            assert got["stream_include_regex"] == r"EPL|Premier"
            assert got["stream_include_regex_enabled"] is True
            assert got["custom_regex_teams"] == r"(?P<team1>\w+) v (?P<team2>\w+)"
            assert got["custom_regex_teams_enabled"] is True

    def test_clearing_a_pattern_also_disables_it(self, isolated_db):
        gid = _make_group(
            "A", stream_exclude_regex=r"\(ALT\)", stream_exclude_regex_enabled=True
        )
        assert _get(gid)["stream_exclude_regex_enabled"] is True

        resp = client.put(
            "/api/v1/groups/bulk",
            json={"group_ids": [gid], "clear_stream_exclude_regex": True},
        )
        assert resp.status_code == 200, resp.text
        got = _get(gid)
        assert got["stream_exclude_regex"] is None
        assert got["stream_exclude_regex_enabled"] is False

    def test_unmentioned_fields_are_left_alone(self, isolated_db):
        gid = _make_group(
            "A",
            custom_regex_date=r"(?P<day>\d+)/(?P<month>\d+)",
            custom_regex_date_enabled=True,
            skip_builtin_filter=True,
        )

        resp = client.put(
            "/api/v1/groups/bulk",
            json={"group_ids": [gid], "custom_regex_league": r"(?P<league>NHL)"},
        )
        assert resp.status_code == 200, resp.text
        got = _get(gid)
        assert got["custom_regex_date"] == r"(?P<day>\d+)/(?P<month>\d+)"
        assert got["custom_regex_date_enabled"] is True
        assert got["skip_builtin_filter"] is True
        assert got["custom_regex_league"] == r"(?P<league>NHL)"
        assert got["custom_regex_league_enabled"] is True

    def test_skip_builtin_filter_is_bulk_settable(self, isolated_db):
        a, b = _make_group("A"), _make_group("B", skip_builtin_filter=True)

        resp = client.put(
            "/api/v1/groups/bulk", json={"group_ids": [a, b], "skip_builtin_filter": False}
        )
        assert resp.status_code == 200, resp.text
        assert _get(a)["skip_builtin_filter"] is False
        assert _get(b)["skip_builtin_filter"] is False


class TestBulkSubscriptionOverride:
    def test_set_and_clear_subscription_leagues(self, isolated_db):
        a, b = _make_group("A"), _make_group("B")

        resp = client.put(
            "/api/v1/groups/bulk",
            json={"group_ids": [a, b], "subscription_leagues": ["nfl", "eng.1"]},
        )
        assert resp.status_code == 200, resp.text
        assert _get(a)["subscription_leagues"] == ["nfl", "eng.1"]
        assert _get(b)["subscription_leagues"] == ["nfl", "eng.1"]

        resp = client.put(
            "/api/v1/groups/bulk",
            json={"group_ids": [a], "clear_subscription_leagues": True},
        )
        assert resp.status_code == 200, resp.text
        assert _get(a)["subscription_leagues"] is None
        assert _get(b)["subscription_leagues"] == ["nfl", "eng.1"]
