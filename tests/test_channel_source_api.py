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


def test_channel_source_channels_lists_selected_groups_without_teamarr_channels(
    tmp_path, monkeypatch
):
    """The Dispatcharr Channel rule picker (#971): channels of the selected
    groups, never Teamarr's own output channels."""
    from types import SimpleNamespace

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    with get_db() as conn:
        conn.execute("UPDATE settings SET epg_channel_source_groups = '[7]' WHERE id = 1")
        conn.execute(
            "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name, "
            "dispatcharr_channel_id) VALUES ('e', 'espn', 't', 'Teamarr output', 900)"
        )

    def channel(cid, name, group):
        return SimpleNamespace(id=cid, name=name, channel_number="1", channel_group_id=group)

    fake = SimpleNamespace(
        m3u=SimpleNamespace(
            list_groups=lambda: [
                SimpleNamespace(id=7, name="US Sports"),
                SimpleNamespace(id=9, name="UK Sports"),
            ]
        ),
        channels=SimpleNamespace(
            get_channels=lambda: [
                channel(101, "FS1", 7),
                channel(100, "ESPN", 7),
                channel(200, "Sky Sports", 9),
                channel(900, "Teamarr output", 7),
            ]
        ),
    )
    monkeypatch.setattr(
        "teamarr.api.routes.dispatcharr.get_dispatcharr_connection", lambda db_factory: fake
    )

    resp = client.get("/api/v1/dispatcharr/channel-source-channels")

    assert resp.status_code == 200, resp.text
    assert [(c["id"], c["name"], c["group_name"]) for c in resp.json()] == [
        (100, "ESPN", "US Sports"),
        (101, "FS1", "US Sports"),
    ]


# --- #986: the rows follow the saved selection, without waiting for a run ---


@pytest.fixture()
def empty_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    monkeypatch.setattr(
        "teamarr.api.routes.settings.epg._channel_source_group_names",
        lambda: {470: "NFL Local"},
    )


def _save_selection(enabled, groups):
    body = client.get("/api/v1/settings/epg").json()
    body["epg_channel_source_enabled"] = enabled
    body["epg_channel_source_groups"] = groups
    resp = client.put("/api/v1/settings/epg", json=body)
    assert resp.status_code == 200, resp.text


def _source_rows():
    return {
        g["dispatcharr_channel_group_id"]: g
        for g in _listed().values()
        if g["is_channel_source"]
    }


def test_saving_a_selection_creates_its_rows(empty_db):
    assert _source_rows() == {}
    _save_selection(True, [470, 1222])
    rows = _source_rows()
    assert set(rows) == {470, 1222}
    assert rows[470]["display_name"] == "Dispatcharr: NFL Local"
    assert rows[470]["enabled"] is True


def test_deselecting_a_group_delists_its_row(empty_db):
    _save_selection(True, [470, 1222])
    _save_selection(True, [470])
    assert set(_source_rows()) == {470}


def test_turning_the_source_off_delists_every_row(empty_db):
    _save_selection(True, [470])
    _save_selection(False, [470])
    assert _source_rows() == {}


def test_an_unrelated_save_does_not_touch_the_rows(empty_db, monkeypatch):
    _save_selection(True, [470])
    calls = []
    monkeypatch.setattr(
        "teamarr.database.groups.ensure_channel_source_group",
        lambda *a, **k: calls.append(1),
    )
    _save_selection(True, [470])
    assert calls == []


def test_dispatcharr_being_down_does_not_fail_the_save(empty_db, monkeypatch):
    def boom():
        raise RuntimeError("down")

    monkeypatch.setattr("teamarr.api.routes.settings.epg._channel_source_group_names", boom)
    _save_selection(True, [470])
    assert client.get("/api/v1/settings/epg").json()["epg_channel_source_groups"] == [470]
