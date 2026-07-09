"""Stats API endpoints.

Provides centralized access to all processing statistics:
- Current aggregate stats
- Historical run data
- Daily/weekly trends
- Live game stats (games today, live now)
"""

import xml.etree.ElementTree as ET
from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from teamarr.database import get_db
from teamarr.database.settings import get_all_settings
from teamarr.database.stats import (
    RunStatus,
    RunType,
    get_current_stats,
    get_live_xmltv_content,
    get_recent_runs,
)

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
        settings = get_all_settings(conn)
        user_tz = ZoneInfo(settings.epg.epg_timezone)
        now = datetime.now(user_tz)
        today = now.date()

        stats = {
            "team": {"games_today": 0, "live_now": 0, "by_league": {}, "live_events": []},
            "event": {"games_today": 0, "live_now": 0, "by_league": {}, "live_events": []},
        }


        xmltv = get_live_xmltv_content(conn)

        # Parse team EPG XMLTV content
        # Use a shared seen set to dedupe games that appear in multiple teams' XMLTV
        # (e.g., when both Pacers and Bulls are tracked, their game appears in both)
        if epg_type is None or epg_type == "team":
            team_seen: set[tuple[str, str, str]] = set()
            for content in xmltv["team"]:
                _parse_xmltv_for_live_stats(
                    content, stats["team"], now, today, user_tz, team_seen
                )

        # Parse event EPG XMLTV content
        if epg_type is None or epg_type == "event":
            event_seen: set[tuple[str, str, str]] = set()
            for content in xmltv["event"]:
                _parse_xmltv_for_live_stats(
                    content, stats["event"], now, today, user_tz, event_seen
                )

        # Convert by_league dict to sorted list
        for key in ["team", "event"]:
            by_league = stats[key]["by_league"]
            stats[key]["by_league"] = [
                {"league": league.upper(), "count": count}
                for league, count in sorted(by_league.items())
            ]

        return stats


def _parse_xmltv_time(time_str: str) -> datetime | None:
    """Parse XMLTV timestamp (YYYYMMDDHHmmss +ZZZZ)."""
    try:
        # Format: 20251229140000 -0500
        if " " in time_str:
            dt_part, tz_part = time_str.split(" ", 1)
        else:
            dt_part = time_str
            tz_part = "+0000"

        # Parse datetime
        dt = datetime.strptime(dt_part, "%Y%m%d%H%M%S")

        # Parse timezone offset
        tz_sign = 1 if tz_part.startswith("+") else -1
        tz_hours = int(tz_part[1:3])
        tz_minutes = int(tz_part[3:5]) if len(tz_part) >= 5 else 0
        from datetime import timedelta, timezone

        tz_offset = timezone(timedelta(hours=tz_sign * tz_hours, minutes=tz_sign * tz_minutes))
        return dt.replace(tzinfo=tz_offset)
    except (ValueError, IndexError):
        return None


def _parse_xmltv_for_live_stats(
    xmltv_content: str,
    stats: dict,
    now: datetime,
    today,
    user_tz: ZoneInfo,
    seen: set[tuple[str, str, str]],
) -> None:
    """Parse XMLTV content and update stats dict with games today/live now.

    Only counts actual game programmes (not filler like pregame/postgame/idle).
    V2 adds comments inside <programme> for filler: teamarr:filler-pregame, etc.
    Programmes without a filler comment are games.

    Args:
        seen: Shared set to dedupe games across multiple XMLTV files (e.g., when
              both teams in a matchup are tracked).
    """
    try:
        # Parse with comments enabled to detect teamarr metadata
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        root = ET.fromstring(xmltv_content, parser)
    except ET.ParseError:
        return

    for programme in root.findall(".//programme"):
        # Check if this programme has a filler comment inside it
        is_filler = False
        for child in programme:
            # Comments have callable tag (ET.Comment function)
            if callable(child.tag):
                comment_text = child.text or ""
                if comment_text.startswith("teamarr:filler"):
                    is_filler = True
                    break

        # Skip filler programmes
        if is_filler:
            continue

        start_str = programme.get("start", "")
        stop_str = programme.get("stop", "")
        channel_id = programme.get("channel", "")

        # Prefer sub-title (has matchup) over title (often generic "Sports event")
        subtitle_elem = programme.find("sub-title")
        title_elem = programme.find("title")
        title = (
            subtitle_elem.text
            if subtitle_elem is not None and subtitle_elem.text
            else title_elem.text
            if title_elem is not None
            else ""
        )

        # Skip if no timing info
        if not start_str or not stop_str:
            continue

        # Dedupe by channel+start+stop (V1 style)
        prog_key = (channel_id, start_str, stop_str)
        if prog_key in seen:
            continue
        seen.add(prog_key)

        start_time = _parse_xmltv_time(start_str)
        stop_time = _parse_xmltv_time(stop_str)

        if not start_time or not stop_time:
            continue

        # Convert to user timezone for date comparison
        start_local = start_time.astimezone(user_tz)

        # Games today: starts today
        if start_local.date() == today:
            stats["games_today"] += 1

            # Extract league from channel_id (e.g., "MichiganWolverines.ncaam" -> "ncaam")
            league = channel_id.split(".")[-1] if "." in channel_id else "unknown"
            stats["by_league"][league] = stats["by_league"].get(league, 0) + 1

            # Live now: currently in progress
            if start_time <= now <= stop_time:
                stats["live_now"] += 1

                # Add to live_events list for tooltip display
                if "live_events" not in stats:
                    stats["live_events"] = []
                stats["live_events"].append(
                    {
                        "title": title,
                        "channel_id": channel_id,
                        "start_time": start_local.isoformat(),
                        "league": league.upper(),
                    }
                )


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

    with get_db() as conn:
        runs = get_recent_runs(
            conn,
            limit=limit,
            run_type=cast("RunType | None", run_type),
            group_id=group_id,
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
