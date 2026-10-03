"""Channel-source rows through the groups API (#542).

Each selected Dispatcharr channel group is its own source row. The Sources
page lists the active ones so a league scope can be set, but the rest of the
row belongs to the run-time sync: it cannot be renamed, re-typed, enabled,
disabled, deleted or bulk-edited from here.
"""

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.database import get_db, init_db
from teamarr.database.groups import ensure_channel_source_group

client = TestClient(app)


@pytest.fixture()
def rows(tmp_path, monkeypatch):
    """Two active rows (groups 470, 1222) and one for a deselected group (99)."""
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    with get_db() as conn:
        ensure_channel_source_group(
            conn, True, selected_group_ids=[99, 470, 1222], group_names={470: "NFL Local"}
        )
        ensure_channel_source_group(conn, True, selected_group_ids=[470, 1222])
        found = {
            r["dispatcharr_channel_group_id"]: r["id"]
            for r in conn.execute(
                "SELECT id, dispatcharr_channel_group_id FROM event_epg_groups "
                "WHERE is_channel_source = 1"
            )
        }
    return found


def _listed():
    resp = client.get("/api/v1/groups", params={"include_disabled": True})
    assert resp.status_code == 200, resp.text
    return {g["id"]: g for g in resp.json()["groups"]}


def test_active_rows_are_listed_and_marked(rows):
    listed = _listed()
    assert rows[470] in listed and rows[1222] in listed
    row = listed[rows[470]]
    assert row["is_channel_source"] is True
    assert row["dispatcharr_channel_group_id"] == 470
    assert row["display_name"] == "Dispatcharr: NFL Local"


def test_row_for_a_deselected_group_is_not_listed(rows):
    assert rows[99] not in _listed()


def test_league_scope_can_be_set_and_cleared(rows):
    gid = rows[470]
    resp = client.put(f"/api/v1/groups/{gid}", json={"subscription_leagues": ["nfl"]})
    assert resp.status_code == 200, resp.text
    assert resp.json()["subscription_leagues"] == ["nfl"]

    resp = client.put(f"/api/v1/groups/{gid}", json={"clear_subscription_leagues": True})
    assert resp.status_code == 200, resp.text
    assert resp.json()["subscription_leagues"] is None


def test_everything_else_in_an_update_is_ignored(rows):
    """The edit form sends the whole row back; only the scope may land."""
    gid = rows[470]
    resp = client.put(
        f"/api/v1/groups/{gid}",
        json={
            "name": "Renamed",
            "enabled": False,
            "name_match_enabled": True,
            "epg_match_enabled": False,
            "stream_include_regex": "x",
            "subscription_leagues": ["nfl"],
        },
    )
    assert resp.status_code == 200, resp.text
    got = resp.json()
    assert got["subscription_leagues"] == ["nfl"]
    assert got["name"] == "Dispatcharr Channels: NFL Local"
    assert got["enabled"] is True
    assert got["name_match_enabled"] is False
    assert got["epg_match_enabled"] is True
    assert got["stream_include_regex"] is None


@pytest.mark.parametrize(
    ("method", "path"),
    [("delete", ""), ("post", "/enable"), ("post", "/disable")],
)
def test_lifecycle_actions_are_refused(rows, method, path):
    resp = getattr(client, method)(f"/api/v1/groups/{rows[470]}{path}")
    assert resp.status_code == 400
    assert "Matching" in resp.json()["detail"]
    assert rows[470] in _listed()


def test_bulk_edit_skips_channel_sources(rows):
    resp = client.put(
        "/api/v1/groups/bulk", json={"group_ids": [rows[470]], "enabled": False}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_updated"] == 0 and body["total_failed"] == 1
    assert _listed()[rows[470]]["enabled"] is True
