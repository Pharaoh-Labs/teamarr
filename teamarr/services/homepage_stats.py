"""Live EPG stats parsing + homepage widget KPIs (#463).

Two consumers share the XMLTV live-stats parser here:

- ``compute_live_stats`` backs ``GET /stats/live`` (Teamarr dashboard),
  preserving its per-type (team/event) response shape.
- ``get_homepage_kpis`` backs ``GET /stats/homepage`` — a flat, stable-named
  KPI payload purpose-built for external dashboard widgets (gethomepage's
  Custom API widget maps fields by JSON path). Field names are a public
  contract: widget configs reference them, so renames are breaking changes.

The homepage payload is assembled from existing stats sources only and must
stay cheap — dashboard widgets poll on an interval, so no live Dispatcharr
connection test happens here (``dispatcharr_configured`` reflects settings).
"""

import xml.etree.ElementTree as ET
from datetime import date, datetime
from sqlite3 import Connection
from zoneinfo import ZoneInfo

from teamarr.consumers.scheduler import get_scheduler_status
from teamarr.database.channels.crud import count_active_managed_channels
from teamarr.database.settings import get_all_settings
from teamarr.database.stats import get_last_run_kpis, get_live_xmltv_content

__all__ = ["compute_live_stats", "get_homepage_kpis"]


def parse_xmltv_time(time_str: str) -> datetime | None:
    """Parse XMLTV timestamp (YYYYMMDDHHmmss +ZZZZ)."""
    try:
        # Format: 20251229140000 -0500
        if " " in time_str:
            dt_part, tz_part = time_str.split(" ", 1)
        else:
            dt_part = time_str
            tz_part = "+0000"

        dt = datetime.strptime(dt_part, "%Y%m%d%H%M%S")

        tz_sign = 1 if tz_part.startswith("+") else -1
        tz_hours = int(tz_part[1:3])
        tz_minutes = int(tz_part[3:5]) if len(tz_part) >= 5 else 0
        from datetime import timedelta, timezone

        tz_offset = timezone(timedelta(hours=tz_sign * tz_hours, minutes=tz_sign * tz_minutes))
        return dt.replace(tzinfo=tz_offset)
    except (ValueError, IndexError):
        return None


def parse_xmltv_for_live_stats(
    xmltv_content: str,
    stats: dict,
    now: datetime,
    today: date,
    user_tz: ZoneInfo,
    seen: set[tuple[str, str, str]],
    today_keys: set[tuple[str, str]] | None = None,
    live_keys: set[tuple[str, str]] | None = None,
    channel_ids: set[str] | None = None,
) -> None:
    """Parse XMLTV content and update stats dict with games today/live now.

    Only counts actual game programmes (not filler like pregame/postgame/idle).
    V2 adds comments inside <programme> for filler: teamarr:filler-pregame, etc.
    Programmes without a filler comment are games.

    Args:
        seen: Shared set to dedupe games across multiple XMLTV files within one
              EPG type (e.g., when both teams in a matchup are tracked).
        today_keys/live_keys: Optional sets collecting (title, start) identity
              keys for games today / live now. Unlike ``seen`` (keyed by
              channel), these dedupe the same game across team AND event EPGs,
              where it airs on different channels. Falls back to the channel id
              when a programme has no title.
        channel_ids: Optional set collecting <channel> element ids, for
              counting distinct channels in this EPG type.
    """
    try:
        # Parse with comments enabled to detect teamarr metadata
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        root = ET.fromstring(xmltv_content, parser)
    except ET.ParseError:
        return

    if channel_ids is not None:
        for channel in root.findall(".//channel"):
            cid = channel.get("id")
            if cid:
                channel_ids.add(cid)

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

        start_time = parse_xmltv_time(start_str)
        stop_time = parse_xmltv_time(stop_str)

        if not start_time or not stop_time:
            continue

        # Convert to user timezone for date comparison
        start_local = start_time.astimezone(user_tz)

        # Games today: starts today
        if start_local.date() == today:
            stats["games_today"] += 1

            game_key = (title or channel_id, start_str)
            if today_keys is not None:
                today_keys.add(game_key)

            # Extract league from channel_id (e.g., "MichiganWolverines.ncaam" -> "ncaam")
            league = channel_id.split(".")[-1] if "." in channel_id else "unknown"
            stats["by_league"][league] = stats["by_league"].get(league, 0) + 1

            # Live now: currently in progress
            if start_time <= now <= stop_time:
                stats["live_now"] += 1
                if live_keys is not None:
                    live_keys.add(game_key)

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


def compute_live_stats(conn: Connection, epg_type: str | None = None) -> dict:
    """Live game statistics from stored XMLTV, per EPG type (team/event).

    Backs ``GET /stats/live`` — response shape is unchanged from when this
    logic lived in the route.
    """
    settings = get_all_settings(conn)
    user_tz = ZoneInfo(settings.epg.epg_timezone)
    now = datetime.now(user_tz)
    today = now.date()

    stats: dict = {
        "team": {"games_today": 0, "live_now": 0, "by_league": {}, "live_events": []},
        "event": {"games_today": 0, "live_now": 0, "by_league": {}, "live_events": []},
    }

    xmltv = get_live_xmltv_content(conn)

    # Use a shared seen set per type to dedupe games that appear in multiple
    # teams' XMLTV (e.g., when both Pacers and Bulls are tracked, their game
    # appears in both)
    if epg_type is None or epg_type == "team":
        team_seen: set[tuple[str, str, str]] = set()
        for content in xmltv["team"]:
            parse_xmltv_for_live_stats(content, stats["team"], now, today, user_tz, team_seen)

    if epg_type is None or epg_type == "event":
        event_seen: set[tuple[str, str, str]] = set()
        for content in xmltv["event"]:
            parse_xmltv_for_live_stats(content, stats["event"], now, today, user_tz, event_seen)

    # Convert by_league dict to sorted list
    for key in ["team", "event"]:
        by_league = stats[key]["by_league"]
        stats[key]["by_league"] = [
            {"league": league.upper(), "count": count}
            for league, count in sorted(by_league.items())
        ]

    return stats


def get_homepage_kpis(conn: Connection) -> dict:
    """Flat KPI payload for external dashboard widgets.

    games_today / live_now are unique games across BOTH team and event EPGs
    (a tracked team's game appearing on a team channel and an event channel
    counts once). Run/match figures come from the latest full_epg run.
    """
    settings = get_all_settings(conn)
    user_tz = ZoneInfo(settings.epg.epg_timezone)
    now = datetime.now(user_tz)
    today = now.date()

    xmltv = get_live_xmltv_content(conn)
    today_keys: set[tuple[str, str]] = set()
    live_keys: set[tuple[str, str]] = set()
    team_channel_ids: set[str] = set()

    # Throwaway per-type accumulators — only the cross-type key sets matter here
    for epg_type, channel_ids in (("team", team_channel_ids), ("event", None)):
        seen: set[tuple[str, str, str]] = set()
        scratch: dict = {"games_today": 0, "live_now": 0, "by_league": {}, "live_events": []}
        for content in xmltv[epg_type]:
            parse_xmltv_for_live_stats(
                content,
                scratch,
                now,
                today,
                user_tz,
                seen,
                today_keys=today_keys,
                live_keys=live_keys,
                channel_ids=channel_ids,
            )

    channels_event = count_active_managed_channels(conn)
    channels_team = len(team_channel_ids)

    run = get_last_run_kpis(conn)
    matched = (run.get("streams_matched") or 0) if run else 0
    unmatched = (run.get("streams_unmatched") or 0) if run else 0
    denom = matched + unmatched
    match_percent = round(100 * matched / denom, 1) if denom else None

    last_run_at = None
    if run and run.get("completed_at"):
        last_run_at = run["completed_at"].astimezone(user_tz).isoformat()

    scheduler = get_scheduler_status()

    return {
        "live_now": len(live_keys),
        "games_today": len(today_keys),
        "channels_total": channels_team + channels_event,
        "channels_team": channels_team,
        "channels_event": channels_event,
        "programmes_total": (run.get("programmes_total") or 0) if run else 0,
        "streams_matched": matched,
        "streams_unmatched": unmatched,
        "match_percent": match_percent,
        "last_run_status": run.get("status") if run else None,
        "last_run_at": last_run_at,
        "next_run_at": scheduler.get("next_run"),
        "scheduler_running": scheduler.get("running", False),
        "dispatcharr_configured": bool(settings.dispatcharr.enabled and settings.dispatcharr.url),
    }
