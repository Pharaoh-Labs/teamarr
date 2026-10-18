"""v102 removes the LFA league from existing installs (#1083)."""

import json

from teamarr.database.migrations.versioned import _migrate_v102_remove_lfa, _run_migrations


def test_lfa_row_subscriptions_and_caches_go_other_leagues_stay(db_conn):
    conn = db_conn
    conn.execute(
        "INSERT OR REPLACE INTO leagues (league_code, provider, provider_league_id, "
        "display_name, sport) VALUES ('lfa', 'espn', 'mma/lfa', 'Legacy Fighting Alliance', 'mma')"
    )
    conn.execute(
        "UPDATE sports_subscription SET leagues = ?, auto_source_leagues = ? WHERE id = 1",
        (json.dumps(["ufc", "lfa", "nfl"]), json.dumps(["lfa"])),
    )
    conn.execute(
        "INSERT INTO event_epg_groups (name, leagues, subscription_leagues) VALUES ('MMA', ?, ?)",
        (json.dumps(["lfa", "pfl"]), json.dumps(["lfa"])),
    )
    conn.execute(
        "INSERT INTO team_cache (team_name, provider, provider_team_id, league, sport) "
        "VALUES ('LFA', 'espn', '1', 'lfa', 'mma')"
    )
    _migrate_v102_remove_lfa(conn)
    assert conn.execute("SELECT count(*) FROM leagues WHERE league_code = 'lfa'").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM leagues WHERE league_code = 'ufc'").fetchone()[0] == 1
    sub = conn.execute(
        "SELECT leagues, auto_source_leagues FROM sports_subscription WHERE id = 1"
    ).fetchone()
    assert json.loads(sub["leagues"]) == ["ufc", "nfl"]
    assert json.loads(sub["auto_source_leagues"]) == []
    group = conn.execute(
        "SELECT leagues, subscription_leagues FROM event_epg_groups WHERE name = 'MMA'"
    ).fetchone()
    assert json.loads(group["leagues"]) == ["pfl"]
    assert json.loads(group["subscription_leagues"]) == []
    assert conn.execute("SELECT count(*) FROM team_cache WHERE league = 'lfa'").fetchone()[0] == 0
    _migrate_v102_remove_lfa(conn)  # idempotent


def test_versioned_upgrade_lands_on_latest_without_lfa(db_conn):
    db_conn.execute("UPDATE settings SET schema_version = 101")
    _run_migrations(db_conn)
    assert db_conn.execute("SELECT schema_version FROM settings").fetchone()[0] >= 102
    assert (
        db_conn.execute("SELECT count(*) FROM leagues WHERE league_code = 'lfa'").fetchone()[0] == 0
    )
