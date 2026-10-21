"""Sources page folders, auto-arrange, undo and league chips (#1110).

All of it is cosmetic (#1109): nothing here may touch processing order or
stream priority, so the tests read only event_epg_groups.folder_id /
sort_order and the folder rows.
"""

import pytest
from fastapi.testclient import TestClient

from teamarr.api.app import app
from teamarr.database import get_db, init_db
from teamarr.database.source_folders import (
    AUTO_ARRANGE_SHARE,
    MULTI_FOLDER,
    arrange_by_evidence,
    arrange_by_provider,
    clear_folders,
    create_folder,
    delete_folder,
    has_undo,
    list_folders,
    restore_arrangement,
    set_arrangement,
)
from teamarr.database.source_league_shares import get_group_league_shares

client = TestClient(app)


def _source(conn, name, account="Acme IPTV", account_id=1, channel_source=False, enabled=True):
    cursor = conn.execute(
        "INSERT INTO event_epg_groups"
        " (name, leagues, m3u_group_id, m3u_group_name, m3u_account_id, m3u_account_name,"
        "  is_channel_source, enabled, sort_order)"
        " VALUES (?, '[]', ?, ?, ?, ?, ?, ?, (SELECT COALESCE(MAX(sort_order), -1) + 1"
        "  FROM event_epg_groups))",
        (name, 1000, name, account_id, account, int(channel_source), int(enabled)),
    )
    return cursor.lastrowid


def _run(conn, run_id, status="completed"):
    conn.execute(
        "INSERT INTO processing_runs (id, run_type, started_at, completed_at, status)"
        " VALUES (?, 'full_epg', '2026-10-21 04:00:00', '2026-10-21 04:03:00', ?)",
        (run_id, status),
    )


def _match(conn, run_id, group_id, stream_id, league, excluded=None):
    conn.execute(
        "INSERT INTO epg_matched_streams"
        " (run_id, group_id, stream_id, stream_name, event_id, event_name, detected_league,"
        "  exclusion_reason)"
        " VALUES (?, ?, ?, ?, 'e', 'E', ?, ?)",
        (run_id, group_id, stream_id, f"s{stream_id}", league, excluded),
    )


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    yield


@pytest.fixture()
def seeded(db):
    """Five sources across two accounts plus a channel source, and one run."""
    with get_db() as conn:
        ids = {
            "nhl": _source(conn, "USA | NHL Teams"),
            "tsn": _source(conn, "Canada | TSN+", account="Maple", account_id=2),
            "f1": _source(conn, "Live | F1 TV", account="Maple", account_id=2),
            "quiet": _source(conn, "Sports | Nothing Yet"),
            "chan": _source(conn, "Dispatcharr Channels", channel_source=True),
            "off": _source(conn, "Dispatcharr Channels (off)", channel_source=True, enabled=False),
        }
        _run(conn, 1)
        _run(conn, 2)
        # Run 1 is older evidence and must be ignored.
        _match(conn, 1, ids["nhl"], 1, "college-football")
        # Run 2: NHL source is 32 NHL + 1 stray; TSN+ is mixed; F1 TV is pure.
        for i in range(32):
            _match(conn, 2, ids["nhl"], 100 + i, "nhl")
        _match(conn, 2, ids["nhl"], 200, "college-football")
        for i in range(54):
            _match(conn, 2, ids["tsn"], 300 + i, "f1")
        for i in range(29):
            _match(conn, 2, ids["tsn"], 400 + i, "college-football")
        for i in range(10):
            _match(conn, 2, ids["f1"], 500 + i, "f1")
        # An excluded match never reaches a channel and never counts.
        _match(conn, 2, ids["f1"], 600, "nascar", excluded="league_not_included")
        # Run 3 was interrupted after one source: not "the last run".
        _run(conn, 3, status="failed")
        _match(conn, 3, ids["quiet"], 700, "nhl")
        conn.commit()
    return ids


class TestLeagueShares:
    def test_shares_come_from_the_last_completed_run_and_exclude_excluded(self, seeded):
        with get_db() as conn:
            run_at, shares = get_group_league_shares(conn)
        assert run_at == "2026-10-21 04:03:00"
        nhl = shares[seeded["nhl"]]
        assert [(s.league, s.count) for s in nhl] == [("nhl", 32), ("college-football", 1)]
        assert nhl[0].share == 0.97 and nhl[0].display_name == "NHL"
        assert [(s.league, s.share) for s in shares[seeded["f1"]]] == [("f1", 1.0)]
        assert seeded["quiet"] not in shares

    def test_list_route_carries_the_chips(self, seeded):
        groups = {g["name"]: g for g in client.get("/api/v1/groups").json()["groups"]}
        chips = groups["Canada | TSN+"]["league_shares"]
        assert [(c["display_name"], c["share"]) for c in chips][:2] == [
            ("F1", 0.651),
            ("NCAAF", 0.349),
        ]
        assert groups["Canada | TSN+"]["league_shares_run_at"] == "2026-10-21 04:03:00"
        assert groups["Sports | Nothing Yet"]["league_shares"] == []
        assert groups["Sports | Nothing Yet"]["folder_id"] is None


class TestArrange:
    def _filing(self):
        with get_db() as conn:
            folders = {f.id: f.name for f in list_folders(conn)}
            rows = conn.execute("SELECT name, folder_id FROM event_epg_groups").fetchall()
        return {r["name"]: folders.get(r["folder_id"]) for r in rows}

    def test_by_provider(self, seeded):
        with get_db() as conn:
            result = arrange_by_provider(conn)
            order = [f.name for f in list_folders(conn)]
        assert (result.folders, result.filed, result.unfiled) == (3, 5, 0)
        assert order == ["Acme IPTV", "Maple", "Dispatcharr channels"]
        filing = self._filing()
        assert filing["USA | NHL Teams"] == "Acme IPTV"
        assert filing["Live | F1 TV"] == "Maple"
        assert filing["Dispatcharr Channels"] == "Dispatcharr channels"
        # A deselected channel-source row is not listed and is not filed.
        assert filing["Dispatcharr Channels (off)"] is None

    def test_by_league_files_at_the_threshold_and_multi_below_it(self, seeded):
        assert AUTO_ARRANGE_SHARE == 0.8
        with get_db() as conn:
            result = arrange_by_evidence(conn, "league")
            order = [f.name for f in list_folders(conn)]
        filing = self._filing()
        assert filing["USA | NHL Teams"] == "NHL"  # 97%: one stray match is not "mixed"
        assert filing["Live | F1 TV"] == "F1"
        assert filing["Canada | TSN+"] == MULTI_FOLDER  # 65%
        assert filing["Sports | Nothing Yet"] is None  # no matches: top level
        assert filing["Dispatcharr Channels"] is None
        assert order == ["F1", "NHL", MULTI_FOLDER]
        assert (result.filed, result.unfiled) == (3, 2)

    def test_by_sport_folds_leagues_into_their_sport(self, seeded):
        with get_db() as conn:
            arrange_by_evidence(conn, "sport")
        filing = self._filing()
        assert filing["USA | NHL Teams"] == "Hockey"
        assert filing["Live | F1 TV"] == "Racing"
        assert filing["Canada | TSN+"] == MULTI_FOLDER

    def test_unknown_arrangement_is_refused(self, seeded):
        with get_db() as conn, pytest.raises(ValueError):
            arrange_by_evidence(conn, "team")


class TestUndo:
    def test_arrange_then_undo_restores_folders_ids_and_positions(self, seeded):
        with get_db() as conn:
            mine = create_folder(conn, "My picks")
            set_arrangement(
                conn,
                [(seeded["nhl"], mine.id, 0), (seeded["f1"], mine.id, 1), (seeded["tsn"], None, 7)],
            )
            assert not has_undo(conn)
            arrange_by_provider(conn)
            assert has_undo(conn)
            assert restore_arrangement(conn)
            folders = list_folders(conn)
            rows = {
                r["id"]: (r["folder_id"], r["sort_order"])
                for r in conn.execute("SELECT id, folder_id, sort_order FROM event_epg_groups")
            }
        assert [(f.id, f.name) for f in folders] == [(mine.id, "My picks")]
        assert rows[seeded["nhl"]] == (mine.id, 0)
        assert rows[seeded["f1"]] == (mine.id, 1)
        assert rows[seeded["tsn"]] == (None, 7)
        with get_db() as conn:
            assert not has_undo(conn)  # one level
            assert not restore_arrangement(conn)

    def test_clear_is_undoable_and_keeps_positions(self, seeded):
        with get_db() as conn:
            arrange_by_provider(conn)
            before = dict(conn.execute("SELECT id, sort_order FROM event_epg_groups").fetchall())
            removed = clear_folders(conn)
            assert removed == 3
            assert list_folders(conn) == []
            assert (
                conn.execute(
                    "SELECT COUNT(*) FROM event_epg_groups WHERE folder_id IS NOT NULL"
                ).fetchone()[0]
                == 0
            )
            assert dict(conn.execute("SELECT id, sort_order FROM event_epg_groups")) == before
            assert restore_arrangement(conn)
            assert len(list_folders(conn)) == 3

    def test_delete_folder_unfiles_without_touching_positions(self, seeded):
        with get_db() as conn:
            folder = create_folder(conn, "Temp")
            set_arrangement(conn, [(seeded["nhl"], folder.id, 3)])
            assert delete_folder(conn, folder.id)
            row = conn.execute(
                "SELECT folder_id, sort_order FROM event_epg_groups WHERE id = ?",
                (seeded["nhl"],),
            ).fetchone()
        assert (row["folder_id"], row["sort_order"]) == (None, 3)

    def test_dropping_into_a_missing_folder_lands_at_top_level(self, seeded):
        with get_db() as conn:
            set_arrangement(conn, [(seeded["nhl"], 9999, 0)])
            row = conn.execute(
                "SELECT folder_id FROM event_epg_groups WHERE id = ?", (seeded["nhl"],)
            ).fetchone()
        assert row["folder_id"] is None


class TestRoutes:
    def test_folder_lifecycle_over_the_api(self, seeded):
        created = client.post("/api/v1/source-folders", json={"name": "  Weekend  "})
        assert created.status_code == 201 and created.json()["name"] == "Weekend"
        fid = created.json()["id"]
        assert client.patch(f"/api/v1/source-folders/{fid}", json={"collapsed": True}).json()[
            "collapsed"
        ]
        put = client.put(
            "/api/v1/source-folders/arrangement",
            json={
                "sources": [{"group_id": seeded["nhl"], "folder_id": fid, "sort_order": 0}],
                "folders": [{"folder_id": fid, "sort_order": 5}],
            },
        )
        assert put.json() == {"updated": 1}
        listed = client.get("/api/v1/source-folders").json()
        assert listed == {
            "folders": [{"id": fid, "name": "Weekend", "sort_order": 5, "collapsed": True}],
            "can_undo": False,
        }
        assert client.delete(f"/api/v1/source-folders/{fid}").status_code == 204
        assert client.delete(f"/api/v1/source-folders/{fid}").status_code == 404

    def test_arrange_undo_and_clear_over_the_api(self, seeded):
        assert client.post("/api/v1/source-folders/undo").status_code == 404
        arranged = client.post("/api/v1/source-folders/arrange", json={"by": "league"}).json()
        assert arranged == {"folders": 3, "filed": 3, "unfiled": 2, "can_undo": True}
        assert client.post("/api/v1/source-folders/arrange", json={"by": "team"}).status_code == 422
        undone = client.post("/api/v1/source-folders/undo").json()
        assert undone == {"folders": [], "can_undo": False}
        client.post("/api/v1/source-folders/arrange", json={"by": "provider"})
        cleared = client.post("/api/v1/source-folders/clear").json()
        assert cleared == {"folders": [], "can_undo": True}
