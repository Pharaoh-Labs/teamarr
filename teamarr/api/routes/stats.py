"""Stats API endpoints.

Provides centralized access to all processing statistics:
- Current aggregate stats
- Historical run data
- Daily/weekly trends
- Live game stats (games today, live now)
"""

from typing import cast

from fastapi import APIRouter, Query

from teamarr.database import get_db
from teamarr.database.stats import (
    RunStatus,
    RunType,
    get_current_stats,
    get_recent_runs,
)
from teamarr.services.homepage_stats import compute_live_stats, get_homepage_kpis

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

    with get_db() as conn:
        return get_current_stats(conn)


@router.get("/live")
def get_live_stats(
    epg_type: str | None = Query(None, description="Filter by 'team' or 'event'"),
):
    """Get live game statistics from the EPG.

    Parses stored XMLTV content to calculate:
    - games_today: Events scheduled for today
    - live_now: Events currently in progress

    Returns:
        team: stats for team-based EPG
        event: stats for event-based EPG
        today_events: list of games scheduled today with start times
    """
    with get_db() as conn:
        return compute_live_stats(conn, epg_type)


@router.get("/homepage")
def get_homepage_stats():
    """Flat KPI payload for external dashboard widgets (gethomepage Custom API).

    Stable field names — widget configs reference them by JSON path:
    live_now, games_today, channels_total/team/event, programmes_total,
    streams_matched, streams_unmatched, match_percent, last_run_status,
    last_run_at, next_run_at, scheduler_running, dispatcharr_configured.

    Cheap by design (widgets poll on an interval): composed from stored
    XMLTV and run stats; no live Dispatcharr connection test.
    """
    with get_db() as conn:
        return get_homepage_kpis(conn)


# =============================================================================
# PROCESSING RUNS
# =============================================================================


@router.get("/runs")
def get_runs(
    limit: int = Query(50, ge=1, le=500, description="Max runs to return"),
    run_type: str | None = Query(None, description="Filter by run type"),
    status: str | None = Query(None, description="Filter by status"),
):
    """Get recent processing runs.

    Returns detailed information about recent processing runs
    with optional filtering.
    """

    with get_db() as conn:
        runs = get_recent_runs(
            conn,
            limit=limit,
            run_type=cast("RunType | None", run_type),
            status=cast("RunStatus | None", status),
        )
        return {
            "runs": [run.to_dict() for run in runs],
            "count": len(runs),
        }


# =============================================================================
# MAINTENANCE
# =============================================================================

# NOTE: run cleanup has no endpoint — cleanup_old_runs(days=30) runs
# automatically after each generation run (consumers/generation.py).


@router.delete("/runs")
def clear_all_runs():
    """Delete all processing runs.

    Used by the Settings UI to clear all run history.
    """
    from teamarr.database.stats import clear_all_runs

    with get_db() as conn:
        deleted = clear_all_runs(conn)
        return {
            "deleted": deleted,
            "message": f"Cleared {deleted} run(s) from history",
        }
