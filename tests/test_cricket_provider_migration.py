"""Offline franchise-cricket identity migration; never discard user configuration."""

import json

import pytest

from teamarr.database.migrations.cricket import CRICKET_TEAMS, migrate_franchise_cricket
from teamarr.database.migrations.versioned import _run_migrations


def add_team(conn, name="Seattle Orcas", old_id="old-seattle", league="mlc", provider="tsdb"):
    return conn.execute(
        "INSERT INTO teams(provider,provider_team_id,primary_league,leagues,sport,team_name,"
        "channel_id,channel_logo_url,managed_channel_enabled) VALUES(?,?,?,?,?,?,?,?,1)",
        (
            provider,
            old_id,
            league,
            json.dumps([league]),
            "cricket",
            name,
            f"{provider}-{old_id}",
            "https://user.example/custom.png",
        ),
    ).lastrowid


def test_versioned_upgrade_preserves_team_channel_identity_and_settings(db_conn):
    conn = db_conn
    team_id = add_team(conn)
    conn.execute(
        "INSERT INTO managed_team_channels(team_id,channel_number,dispatcharr_channel_id) "
        "VALUES(?,123,999)",
        (team_id,),
    )
    conn.execute(
        "INSERT INTO team_aliases(alias,league,provider,team_id,team_name) "
        "VALUES('my orcas','mlc','tsdb','old-seattle','Seattle Orcas')"
    )
    conn.execute(
        "INSERT INTO channel_priority_teams(provider,provider_team_id,team_name,league,sport) "
        "VALUES('tsdb','old-seattle','Seattle Orcas','mlc','cricket')"
    )
    conn.execute(
        "INSERT INTO numbering_exceptions(scope,sport,provider,provider_team_id,team_name,start) "
        "VALUES('team','cricket','tsdb','old-seattle','Seattle Orcas',800)"
    )
    conn.execute("UPDATE settings SET schema_version=99")
    _run_migrations(conn)
    team = conn.execute("SELECT * FROM teams WHERE id=?", (team_id,)).fetchone()
    assert (team["provider"], team["provider_team_id"]) == ("espn", "1381359")
    assert team["channel_id"] == "tsdb-old-seattle"
    assert team["channel_logo_url"] == "https://user.example/custom.png"
    assert team["managed_channel_enabled"] == 1
    managed = conn.execute(
        "SELECT * FROM managed_team_channels WHERE team_id=?", (team_id,)
    ).fetchone()
    assert managed["dispatcharr_channel_id"] == 999 and managed["channel_number"] == 123
    assert conn.execute("SELECT provider,team_id FROM team_aliases").fetchone()[:] == (
        "espn",
        "1381359",
    )
    assert conn.execute("SELECT provider,provider_team_id FROM channel_priority_teams").fetchone()[
        :
    ] == ("espn", "1381359")
    pin = conn.execute("SELECT * FROM numbering_exceptions").fetchone()
    assert (pin["provider"], pin["provider_team_id"], pin["start"]) == ("espn", "1381359", 800)
    assert conn.execute("SELECT schema_version FROM settings").fetchone()[0] == 100
    _run_migrations(conn)
    assert conn.execute("SELECT count(*) FROM teams").fetchone()[0] == 1


def test_all_captured_teams_and_renamed_clubs_migrate_offline(db_conn):
    conn = db_conn
    for league, teams in CRICKET_TEAMS.items():
        for n, (name, new_id) in enumerate(teams.items()):
            old_id = f"old-{league}-{n}"
            team_id = add_team(conn, name, old_id, league)
            migrate_franchise_cricket(conn)
            row = conn.execute(
                "SELECT provider,provider_team_id FROM teams WHERE id=?", (team_id,)
            ).fetchone()
            assert row[:] == ("espn", new_id)
            conn.execute("DELETE FROM teams WHERE id=?", (team_id,))


def test_json_id_only_filters_learn_names_before_cache_is_cleared(db_conn):
    conn = db_conn
    conn.execute(
        "INSERT INTO team_cache(team_name,provider,provider_team_id,league,sport) "
        "VALUES('Texas Super Kings','tsdb','old-texas','mlc','cricket')"
    )
    entries = [
        {"provider": "tsdb", "team_id": "old-texas", "league": "mlc"},
        {"provider": "tsdb", "team_id": "old-mi", "league": "mlc", "name": "MI New York"},
        {"provider": "tsdb", "team_id": "leave", "league": "boxing", "name": "Other"},
    ]
    conn.execute(
        "UPDATE settings SET default_include_teams=?,default_exclude_teams=?",
        (json.dumps(entries), json.dumps(entries)),
    )
    conn.execute(
        "INSERT INTO event_epg_groups(name,leagues,include_teams,exclude_teams) "
        "VALUES('Cricket','[\"mlc\"]',?,?)",
        (json.dumps(entries), json.dumps(entries)),
    )
    migrate_franchise_cricket(conn)
    for table, field in [
        ("settings", "default_include_teams"),
        ("settings", "default_exclude_teams"),
        ("event_epg_groups", "include_teams"),
        ("event_epg_groups", "exclude_teams"),
    ]:
        result = json.loads(conn.execute(f"SELECT {field} FROM {table}").fetchone()[0])
        assert result[0] == {"provider": "espn", "team_id": "1381353", "league": "mlc"}
        assert result[1]["provider"] == "espn" and result[1]["team_id"] == "1381355"
        assert result[2] == entries[2]
    assert conn.execute("SELECT count(*) FROM team_cache WHERE league='mlc'").fetchone()[0] == 0


def test_unrecognized_and_duplicate_configurations_are_kept_not_widened(db_conn, caplog):
    conn = db_conn
    unknown = add_team(conn, "Unknown Club", "unknown")
    add_team(conn, "Seattle Orcas", "1381359", provider="espn")
    duplicate = add_team(conn)
    unmapped = [{"provider": "tsdb", "team_id": "unknown", "league": "mlc"}]
    conn.execute("UPDATE settings SET default_exclude_teams=?", (json.dumps(unmapped),))
    migrate_franchise_cricket(conn)
    assert conn.execute("SELECT provider FROM teams WHERE id=?", (unknown,)).fetchone()[0] == "tsdb"
    assert (
        conn.execute("SELECT provider FROM teams WHERE id=?", (duplicate,)).fetchone()[0] == "tsdb"
    )
    assert (
        json.loads(conn.execute("SELECT default_exclude_teams FROM settings").fetchone()[0])
        == unmapped
    )
    assert "preserved for review" in caplog.text


def test_conflicting_names_for_same_old_identity_require_review(db_conn, caplog):
    conn = db_conn
    team_id = add_team(conn, "Seattle Orcas", "same-id")
    conn.execute(
        "INSERT INTO team_cache(team_name,provider,provider_team_id,league,sport) "
        "VALUES('MI New York','tsdb','same-id','mlc','cricket')"
    )
    migrate_franchise_cricket(conn)
    row = conn.execute(
        "SELECT provider,provider_team_id FROM teams WHERE id=?", (team_id,)
    ).fetchone()
    assert row[:] == ("tsdb", "same-id")
    assert "conflicting mlc identity" in caplog.text


def test_cached_results_clear_but_pins_and_dispatcharr_ownership_survive(db_conn):
    conn = db_conn
    for key in [
        "events:mlc:2026",
        "events_raw:TSDBProvider:mlc:2026",
        "event:ipl:old",
        "events:nfl:2026",
    ]:
        conn.execute(
            "INSERT INTO service_cache(cache_key,data_json,expires_at) VALUES(?,'[]','2099-01-01')",
            (key,),
        )
    for fingerprint, league, event_id, pinned in [
        ("normal", "mlc", "old-game", 0),
        ("pin", "mlc", "old-game", 1),
        ("skip", "mlc", "__USER_SKIPPED__", 1),
        ("negative", "unknown", "__FAILED__", 0),
        ("other", "nfl", "other-game", 0),
    ]:
        conn.execute(
            "INSERT INTO stream_match_cache(fingerprint,group_id,stream_id,stream_name,"
            "event_id,league,user_corrected) VALUES(?,1,1,'name',?,?,?)",
            (fingerprint, event_id, league, pinned),
        )
    conn.execute(
        "INSERT INTO managed_channels(event_id,event_provider,tvg_id,channel_name,league,"
        "dispatcharr_channel_id,scheduled_delete_at) "
        "VALUES('old-game','tsdb','same-tvg','Old game','mlc',999,'2026-07-19')"
    )
    migrate_franchise_cricket(conn)
    assert [r[0] for r in conn.execute("SELECT cache_key FROM service_cache")] == [
        "events:nfl:2026"
    ]
    assert {r[0] for r in conn.execute("SELECT fingerprint FROM stream_match_cache")} == {
        "pin",
        "skip",
        "other",
    }
    old = conn.execute("SELECT * FROM managed_channels").fetchone()
    assert old["deleted_at"] is None and old["dispatcharr_channel_id"] == 999
    assert old["event_provider"] == "tsdb" and old["scheduled_delete_at"] == "2026-07-19"


@pytest.mark.parametrize(
    "value", ["not json", "{}", "null", '[{"provider":"tsdb","league":"mlc","name":12}]']
)
def test_malformed_filter_json_is_not_rewritten(db_conn, value):
    db_conn.execute("UPDATE settings SET default_exclude_teams=?", (value,))
    migrate_franchise_cricket(db_conn)
    assert db_conn.execute("SELECT default_exclude_teams FROM settings").fetchone()[0] == value


def test_fresh_league_mappings_are_espn_and_importable(db_conn):
    for league, slug in {"mlc": "21266", "ipl": "8048", "bbl": "8044", "sa20": "21275"}.items():
        row = db_conn.execute(
            "SELECT provider,provider_league_id,import_enabled FROM leagues WHERE league_code=?",
            (league,),
        ).fetchone()
        assert row[:] == ("espn", f"cricket/{slug}", 1)
