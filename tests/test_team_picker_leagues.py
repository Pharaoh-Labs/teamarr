"""team-picker-leagues carries the configured matching classification (#1131).

The manual-event form filters the picker to configured team_vs_team leagues,
so the endpoint must surface ``leagues.event_type`` alongside the existing
fields. Unconfigured (team_cache-only) leagues report None.
"""

from teamarr.database.team_cache import get_team_picker_leagues


def _seed_team(conn, name, league, provider="espn", team_id=None):
    conn.execute(
        """INSERT INTO team_cache
           (team_name, team_abbrev, team_short_name, provider, provider_team_id,
            league, sport) VALUES (?, ?, ?, ?, ?, ?, 'basketball')""",
        (name, name[:3].upper(), name, provider, team_id or name.lower(), league),
    )


def test_event_type_flows_through_for_configured_and_unconfigured(db_conn):
    db_conn.execute(
        """INSERT INTO leagues (league_code, provider, provider_league_id, display_name,
                                 sport, event_type)
           VALUES ('picker.test', 'espn', 'basketball/x', 'Picker Test',
                   'basketball', 'team_vs_team')"""
    )
    _seed_team(db_conn, "Boston Celtics", "picker.test")
    _seed_team(db_conn, "Miami Heat", "picker.test")
    _seed_team(db_conn, "Some Club", "street.league", provider="tsdb")

    rows = {r["slug"]: r for r in get_team_picker_leagues(db_conn)}

    assert rows["picker.test"]["event_type"] == "team_vs_team"
    assert rows["picker.test"]["is_configured"] is True
    assert rows["street.league"]["event_type"] is None
    assert rows["street.league"]["is_configured"] is False
