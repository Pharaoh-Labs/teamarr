"""Stats API endpoints.

Provides centralized access to all processing statistics:
- Current aggregate stats
- Historical run data
- Daily/weekly trends
"""

from fastapi import APIRouter, Query

from teamarr.database import get_db

router = APIRouter()


# =============================================================================
# CURRENT STATS
# =============================================================================


@router.get("")
def get_stats():
    """Get current aggregate stats.

    Returns all stats from a single endpoint:
    - Overall run counts and performance
    - Stream matching stats (matched, unmatched, cached)
    - Channel lifecycle stats (created, deleted, active)
    - Programme stats by type (events, pregame, postgame, idle)
    - Last 24 hour summary
    - Breakdown by run type
    """
    from teamarr.database.stats import get_current_stats

    with get_db() as conn:
        return get_current_stats(conn)


@router.get("/dashboard")
def get_dashboard_stats():
    """Get aggregated dashboard stats for UI quadrants.

    Returns stats organized for the Dashboard's 4 quadrants:
    - Teams: total, active, assigned, leagues breakdown
    - Event Groups: total, streams, match rates, leagues (from latest run)
    - EPG: channels, events, filler by type (from latest run)
    - Channels: active, logos, groups, deleted
    """
    import json

    with get_db() as conn:
        # Teams stats
        teams_cursor = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN active = 1 THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN template_id IS NOT NULL THEN 1 ELSE 0 END) as assigned
            FROM teams
        """)
        teams_row = teams_cursor.fetchone()

        # Teams by league
        leagues_cursor = conn.execute("""
            SELECT primary_league as league, COUNT(*) as count
            FROM teams
            GROUP BY primary_league
            ORDER BY count DESC
        """)
        team_leagues = [
            {"league": r["league"], "logo_url": None, "count": r["count"]}
            for r in leagues_cursor.fetchall()
        ]

        # Event groups configuration
        groups_cursor = conn.execute("""
            SELECT
                id, name, leagues, total_stream_count
            FROM event_epg_groups
            WHERE enabled = 1
        """)
        groups = groups_cursor.fetchall()

        # Build group name lookup and collect configured leagues
        group_name_lookup = {}
        event_leagues_set: set[str] = set()
        total_streams = 0

        for g in groups:
            group_name_lookup[g["id"]] = g["name"]
            leagues = json.loads(g["leagues"]) if g["leagues"] else []
            event_leagues_set.update(leagues)
            total_streams += g["total_stream_count"] or 0

        event_leagues = [
            {"league": league, "logo_url": None, "count": 1} for league in sorted(event_leagues_set)
        ]

        # Get actual match stats from latest completed run
        latest_run = conn.execute("""
            SELECT id, streams_matched, streams_unmatched, streams_fetched, streams_cached,
                   programmes_total, programmes_events, programmes_pregame,
                   programmes_postgame, programmes_idle,
                   extra_metrics
            FROM processing_runs
            WHERE status = 'completed'
            ORDER BY id DESC
            LIMIT 1
        """).fetchone()

        # Initialize match stats from latest run
        matched_streams = 0
        unmatched_streams = 0
        group_breakdown = []

        if latest_run:
            matched_streams = latest_run["streams_matched"] or 0
            unmatched_streams = latest_run["streams_unmatched"] or 0

            # Get per-group breakdown from matched/failed streams tables
            matched_by_group = conn.execute("""
                SELECT group_id, COUNT(*) as matched
                FROM epg_matched_streams
                WHERE run_id = ?
                GROUP BY group_id
            """, (latest_run["id"],)).fetchall()

            failed_by_group = conn.execute("""
                SELECT group_id, COUNT(*) as failed
                FROM epg_failed_matches
                WHERE run_id = ?
                GROUP BY group_id
            """, (latest_run["id"],)).fetchall()

            # Build lookup for failed counts
            failed_lookup = {r["group_id"]: r["failed"] for r in failed_by_group}

            for r in matched_by_group:
                gid = r["group_id"]
                matched = r["matched"]
                failed = failed_lookup.get(gid, 0)
                group_breakdown.append({
                    "name": group_name_lookup.get(gid, f"Group {gid}"),
                    "matched": matched,
                    "total": matched + failed,
                })

            # Add groups with only failures (no matches)
            matched_gids = {r["group_id"] for r in matched_by_group}
            for gid, failed in failed_lookup.items():
                if gid not in matched_gids:
                    group_breakdown.append({
                        "name": group_name_lookup.get(gid, f"Group {gid}"),
                        "matched": 0,
                        "total": failed,
                    })
        else:
            # No runs yet - show groups with zero matches
            for g in groups:
                stream_count = g["total_stream_count"] or 0
                group_breakdown.append({
                    "name": g["name"],
                    "matched": 0,
                    "total": stream_count,
                })

        # Calculate match percent from actual data
        total_eligible = matched_streams + unmatched_streams
        match_percent = round(matched_streams / total_eligible * 100) if total_eligible > 0 else 0

        # EPG stats from latest run
        epg_stats = {
            "channels_total": 0,
            "channels_team": 0,
            "channels_event": 0,
            "events_total": 0,
            "events_team": 0,
            "events_event": 0,
            "filler_total": 0,
            "filler_pregame": 0,
            "filler_postgame": 0,
            "filler_idle": 0,
            "programmes_total": 0,
        }

        if latest_run:
            extra = json.loads(latest_run["extra_metrics"]) if latest_run["extra_metrics"] else {}
            teams_processed = extra.get("teams_processed", 0)
            groups_processed = extra.get("groups_processed", 0)

            # Total programmes and events
            programmes_total = latest_run["programmes_total"] or 0
            events_total = latest_run["programmes_events"] or 0

            # If we have teams and no groups, all events are team-based
            # If we have groups and no teams, all events are event-based
            # Otherwise estimate based on ratio of teams to groups processed
            if teams_processed > 0 and groups_processed == 0:
                events_team = events_total
                events_event = 0
            elif groups_processed > 0 and teams_processed == 0:
                events_team = 0
                events_event = events_total
            elif teams_processed > 0 and groups_processed > 0:
                # Estimate proportionally
                total_channels = teams_processed + groups_processed
                events_team = int(events_total * teams_processed / total_channels)
                events_event = events_total - events_team
            else:
                events_team = 0
                events_event = 0

            epg_stats["programmes_total"] = programmes_total
            epg_stats["events_total"] = events_total
            epg_stats["events_team"] = events_team
            epg_stats["events_event"] = events_event
            epg_stats["filler_pregame"] = latest_run["programmes_pregame"] or 0
            epg_stats["filler_postgame"] = latest_run["programmes_postgame"] or 0
            epg_stats["filler_idle"] = latest_run["programmes_idle"] or 0
            epg_stats["filler_total"] = (
                epg_stats["filler_pregame"]
                + epg_stats["filler_postgame"]
                + epg_stats["filler_idle"]
            )
            epg_stats["channels_team"] = teams_processed
            epg_stats["channels_event"] = groups_processed
            epg_stats["channels_total"] = teams_processed + groups_processed

        # Managed channels stats
        channels_cursor = conn.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN deleted_at IS NULL THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN logo_url IS NOT NULL AND logo_url != ''
                    THEN 1 ELSE 0 END) as with_logos,
                SUM(CASE WHEN deleted_at IS NOT NULL
                    AND deleted_at > datetime('now', '-1 day')
                    THEN 1 ELSE 0 END) as deleted_24h
            FROM managed_channels
        """)
        channels_row = channels_cursor.fetchone()

        # Channel groups breakdown from managed_channels (by event_epg_group)
        channel_groups_cursor = conn.execute("""
            SELECT mc.event_epg_group_id, eg.name as group_name, COUNT(*) as count
            FROM managed_channels mc
            LEFT JOIN event_epg_groups eg ON mc.event_epg_group_id = eg.id
            WHERE mc.deleted_at IS NULL AND mc.event_epg_group_id IS NOT NULL
            GROUP BY mc.event_epg_group_id
            ORDER BY count DESC
        """)
        channel_group_rows = channel_groups_cursor.fetchall()
        channel_group_breakdown = [
            {
                "id": r["event_epg_group_id"],
                "name": r["group_name"] or f"Group {r['event_epg_group_id']}",
                "count": r["count"],
            }
            for r in channel_group_rows
        ]
        channel_groups = len(channel_group_breakdown)

        return {
            "teams": {
                "total": teams_row["total"] or 0,
                "active": teams_row["active"] or 0,
                "assigned": teams_row["assigned"] or 0,
                "leagues": team_leagues,
            },
            "event_groups": {
                "total": len(groups),
                "streams_total": total_streams,
                "streams_matched": matched_streams,
                "match_percent": match_percent,
                "leagues": event_leagues,
                "groups": group_breakdown,
            },
            "epg": epg_stats,
            "channels": {
                "active": channels_row["active"] or 0,
                "with_logos": channels_row["with_logos"] or 0,
                "groups": channel_groups,
                "deleted_24h": channels_row["deleted_24h"] or 0,
                "group_breakdown": channel_group_breakdown,
            },
        }


@router.get("/history")
def get_stats_history(
    days: int = Query(7, ge=1, le=90, description="Number of days of history"),
    run_type: str | None = Query(None, description="Filter by run type"),
):
    """Get daily stats history for charting.

    Returns per-day aggregates for the specified time range.
    """
    from teamarr.database.stats import get_stats_history as get_history

    with get_db() as conn:
        return get_history(conn, days=days, run_type=run_type)


# =============================================================================
# PROCESSING RUNS
# =============================================================================


@router.get("/runs")
def get_runs(
    limit: int = Query(50, ge=1, le=500, description="Max runs to return"),
    run_type: str | None = Query(None, description="Filter by run type"),
    group_id: int | None = Query(None, description="Filter by group ID"),
    status: str | None = Query(None, description="Filter by status"),
):
    """Get recent processing runs.

    Returns detailed information about recent processing runs
    with optional filtering.
    """
    from teamarr.database.stats import get_recent_runs

    with get_db() as conn:
        runs = get_recent_runs(
            conn,
            limit=limit,
            run_type=run_type,
            group_id=group_id,
            status=status,
        )
        return {
            "runs": [run.to_dict() for run in runs],
            "count": len(runs),
        }


@router.get("/runs/{run_id}")
def get_run(run_id: int):
    """Get a specific processing run by ID."""
    from fastapi import HTTPException, status

    from teamarr.database.stats import get_run as get_run_by_id

    with get_db() as conn:
        run = get_run_by_id(conn, run_id)
        if not run:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Run {run_id} not found",
            )
        return run.to_dict()


# =============================================================================
# MAINTENANCE
# =============================================================================


@router.delete("/runs/cleanup")
def cleanup_runs(
    days: int = Query(30, ge=1, le=365, description="Delete runs older than N days"),
):
    """Delete old processing runs.

    Cleans up historical run data to manage database size.
    """
    from teamarr.database.stats import cleanup_old_runs

    with get_db() as conn:
        deleted = cleanup_old_runs(conn, days=days)
        return {
            "deleted": deleted,
            "message": f"Deleted {deleted} runs older than {days} days",
        }
