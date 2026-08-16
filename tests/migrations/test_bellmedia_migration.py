"""Regression coverage for the CFL provider migration."""

from teamarr.database.migrations import _migrate_v85_cfl_bellmedia


def test_cfl_migration_remaps_known_team_and_clears_cache(db_conn):
    db_conn.execute(
        "INSERT INTO team_cache (team_name, provider, provider_team_id, league, sport) "
        "VALUES ('Winnipeg Blue Bombers', 'tsdb', 'old', 'cfl', 'football')"
    )
    db_conn.execute(
        "INSERT OR REPLACE INTO league_cache (league_slug, provider, sport) "
        "VALUES ('cfl', 'tsdb', 'football')"
    )
    db_conn.execute(
        "INSERT INTO teams (provider, provider_team_id, primary_league, sport, "
        "team_name, channel_id) "
        "VALUES ('tsdb', 'old', 'cfl', 'football', 'Winnipeg Blue Bombers', 'wpg')"
    )
    db_conn.execute(
        "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name, league) "
        "VALUES ('old-event', 'tsdb', 'old-event', 'CFL', 'cfl')"
    )

    _migrate_v85_cfl_bellmedia(db_conn)

    cache_count = db_conn.execute(
        "SELECT COUNT(*) FROM team_cache WHERE league = 'cfl'"
    ).fetchone()[0]
    league_count = db_conn.execute(
        "SELECT COUNT(*) FROM league_cache WHERE league_slug = 'cfl'"
    ).fetchone()[0]
    team = db_conn.execute(
        "SELECT provider, provider_team_id FROM teams WHERE channel_id = 'wpg'"
    ).fetchone()
    assert cache_count == 0
    assert league_count == 0
    assert tuple(team) == ("bellmedia", "110380")
    assert db_conn.execute("SELECT deleted_at FROM managed_channels").fetchone()[0] is not None


def test_cfl_migration_keeps_unknown_team_configuration(db_conn):
    db_conn.execute(
        "INSERT INTO teams (provider, provider_team_id, primary_league, sport, "
        "team_name, channel_id) "
        "VALUES ('tsdb', 'old', 'cfl', 'football', 'Defunct Team', 'defunct')"
    )

    _migrate_v85_cfl_bellmedia(db_conn)

    team = db_conn.execute(
        "SELECT provider, provider_team_id FROM teams WHERE channel_id = 'defunct'"
    ).fetchone()
    assert tuple(team) == ("tsdb", "old")
