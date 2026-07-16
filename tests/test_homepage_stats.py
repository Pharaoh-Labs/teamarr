"""Homepage widget KPI service tests (#463).

Covers get_homepage_kpis (flat payload, cross-EPG game dedupe, match %)
and the compute_live_stats shape preserved for /stats/live.
"""

from datetime import UTC, datetime, timedelta

from teamarr.database.settings import get_all_settings
from teamarr.services.homepage_stats import compute_live_stats, get_homepage_kpis
from teamarr.utilities.tz import now_utc, to_db_utc

# Throwaway test groups use high sentinel ids — low ids collide with real groups
TEST_GROUP_ID = 999990


def _xmltv_time(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime("%Y%m%d%H%M%S +0000")


def _xmltv(channels: list[str], programmes: list[tuple[str, str, str, str]]) -> str:
    """Build minimal XMLTV. programmes = (channel, start, stop, subtitle)."""
    parts = ['<?xml version="1.0" encoding="UTF-8"?><tv>']
    for cid in channels:
        parts.append(f'<channel id="{cid}"><display-name>{cid}</display-name></channel>')
    for cid, start, stop, subtitle in programmes:
        parts.append(
            f'<programme start="{start}" stop="{stop}" channel="{cid}">'
            f"<title>Sports event</title><sub-title>{subtitle}</sub-title>"
            f"</programme>"
        )
    parts.append("</tv>")
    return "".join(parts)


def _seed_team(conn, team_id: int, channel_id: str) -> None:
    conn.execute(
        """
        INSERT INTO teams (id, provider, provider_team_id, primary_league, sport,
                           team_name, channel_id, active)
        VALUES (?, 'espn', ?, 'mlb', 'baseball', ?, ?, 1)
        """,
        (team_id, f"t{team_id}", f"Team {team_id}", channel_id),
    )


def _seed_event_group(conn, group_id: int) -> None:
    conn.execute(
        "INSERT INTO event_epg_groups (id, name, leagues, enabled) VALUES (?, ?, '[\"mlb\"]', 1)",
        (group_id, f"test-group-{group_id}"),
    )


def test_homepage_kpis_empty_db(db_conn):
    kpis = get_homepage_kpis(db_conn)

    assert kpis["live_now"] == 0
    assert kpis["games_today"] == 0
    assert kpis["channels_total"] == 0
    assert kpis["programmes_total"] == 0
    assert kpis["match_percent"] is None
    assert kpis["last_run_status"] is None
    assert kpis["last_run_at"] is None
    assert kpis["scheduler_running"] is False
    assert kpis["dispatcharr_configured"] is False


def test_homepage_kpis_dedupes_games_across_team_and_event_epg(db_conn):
    settings = get_all_settings(db_conn)
    from zoneinfo import ZoneInfo

    now = datetime.now(ZoneInfo(settings.epg.epg_timezone))
    # start=now keeps the game both "today" and "live" regardless of wall clock
    start, stop = _xmltv_time(now), _xmltv_time(now + timedelta(hours=3))

    _seed_team(db_conn, 999991, "DetroitTigers.mlb")
    db_conn.execute(
        "INSERT INTO team_epg_xmltv (team_id, xmltv_content) VALUES (?, ?)",
        (
            999991,
            _xmltv(
                ["DetroitTigers.mlb"],
                [("DetroitTigers.mlb", start, stop, "Tigers vs Twins")],
            ),
        ),
    )

    _seed_event_group(db_conn, TEST_GROUP_ID)
    db_conn.execute(
        "INSERT INTO event_epg_xmltv (group_id, xmltv_content) VALUES (?, ?)",
        (
            TEST_GROUP_ID,
            _xmltv(
                ["teamarr.event.1", "teamarr.event.2"],
                [
                    # Same game as the team channel — must count once
                    ("teamarr.event.1", start, stop, "Tigers vs Twins"),
                    ("teamarr.event.2", start, stop, "Yankees vs Red Sox"),
                ],
            ),
        ),
    )
    db_conn.commit()

    kpis = get_homepage_kpis(db_conn)

    assert kpis["games_today"] == 2
    assert kpis["live_now"] == 2
    assert kpis["channels_team"] == 1
    assert kpis["channels_event"] == 0  # managed_channels table is empty
    assert kpis["channels_total"] == 1


def test_homepage_kpis_last_run_and_match_percent(db_conn):
    now = to_db_utc(now_utc())
    db_conn.execute(
        """
        INSERT INTO processing_runs (run_type, started_at, completed_at, status,
                                     streams_matched, streams_unmatched, programmes_total)
        VALUES ('full_epg', ?, ?, 'completed', 90, 10, 500)
        """,
        (now, now),
    )
    db_conn.commit()

    kpis = get_homepage_kpis(db_conn)

    assert kpis["last_run_status"] == "completed"
    assert kpis["last_run_at"] is not None
    assert kpis["streams_matched"] == 90
    assert kpis["streams_unmatched"] == 10
    assert kpis["match_percent"] == 90.0
    assert kpis["programmes_total"] == 500


def test_compute_live_stats_shape_preserved(db_conn):
    stats = compute_live_stats(db_conn)

    for key in ("team", "event"):
        assert stats[key]["games_today"] == 0
        assert stats[key]["live_now"] == 0
        assert stats[key]["by_league"] == []
        assert stats[key]["live_events"] == []
