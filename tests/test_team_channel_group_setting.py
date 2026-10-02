"""The "Own group / Group with league" setting for managed team channels (#940)."""

import pytest

from teamarr.database.settings import get_dispatcharr_settings, update_dispatcharr_settings


def test_default_is_own_group(db_conn):
    assert get_dispatcharr_settings(db_conn).managed_team_channel_league_groups is False


def test_round_trip_and_untouched_when_not_provided(db_conn):
    update_dispatcharr_settings(db_conn, managed_team_channel_league_groups=True)
    assert get_dispatcharr_settings(db_conn).managed_team_channel_league_groups is True
    # A save that does not mention it (the connection tab) must not reset it.
    update_dispatcharr_settings(db_conn, epg_id=12)
    assert get_dispatcharr_settings(db_conn).managed_team_channel_league_groups is True
    update_dispatcharr_settings(db_conn, managed_team_channel_league_groups=False)
    assert get_dispatcharr_settings(db_conn).managed_team_channel_league_groups is False


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from teamarr.api.app import app
    from teamarr.database.connection import init_db

    path = tmp_path / "test.db"
    init_db(path)
    monkeypatch.setenv("DATABASE_PATH", str(path))
    return TestClient(app)


def test_api_reports_and_updates_the_setting(client):
    assert client.get("/api/v1/settings/dispatcharr").json()[
        "managed_team_channel_league_groups"
    ] is False

    resp = client.put(
        "/api/v1/settings/dispatcharr", json={"managed_team_channel_league_groups": True}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["managed_team_channel_league_groups"] is True

    # An update that omits it leaves it alone.
    resp = client.put("/api/v1/settings/dispatcharr", json={"cleanup_unused_logos": True})
    assert resp.json()["managed_team_channel_league_groups"] is True
