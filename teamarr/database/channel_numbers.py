"""Channel numbering and range management.

Two global modes:
- AUTO: Sequential numbering from channel_range_start, ordered by sort priorities
- MANUAL: Per-league starting channel numbers from league_channel_starts

Sort order is always: sport_priority → league_priority → event_time → event_id
Priorities come from channel_sort_priorities table (drag-drop UI).
"""

import json
import logging
import sqlite3
from datetime import datetime
from sqlite3 import Connection

logger = logging.getLogger(__name__)

MAX_CHANNEL = 999999  # Effectively no limit per Dispatcharr update


# =============================================================================
# Settings Accessors
# =============================================================================


def get_global_channel_range(conn: Connection) -> tuple[int, int | None]:
    """Get global channel range settings.

    Returns:
        Tuple of (range_start, range_end). range_end may be None (no limit).
    """
    cursor = conn.execute(
        "SELECT channel_range_start, channel_range_end FROM settings WHERE id = 1"
    )
    row = cursor.fetchone()
    if not row:
        return 101, None
    return row["channel_range_start"] or 101, row["channel_range_end"]


def get_global_channel_mode(conn: Connection) -> str:
    """Get the global channel numbering mode.

    Returns:
        'auto' or 'manual'
    """
    cursor = conn.execute("SELECT global_channel_mode FROM settings WHERE id = 1")
    row = cursor.fetchone()
    if not row or not row["global_channel_mode"]:
        return "auto"
    mode = row["global_channel_mode"]
    return mode if mode in ("auto", "manual") else "auto"


def get_league_channel_starts(conn: Connection) -> dict[str, int]:
    """Get per-league starting channel numbers for MANUAL mode.

    Returns:
        Dict mapping league_code → starting channel number.
    """
    cursor = conn.execute("SELECT league_channel_starts FROM settings WHERE id = 1")
    row = cursor.fetchone()
    if not row or not row["league_channel_starts"]:
        return {}
    try:
        starts = json.loads(row["league_channel_starts"])
        return {k: int(v) for k, v in starts.items()} if isinstance(starts, dict) else {}
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}


def get_global_consolidation_mode(conn: Connection) -> str:
    """Get the global stream consolidation mode.

    Returns:
        'consolidate' or 'separate'
    """
    try:
        cursor = conn.execute(
            "SELECT global_consolidation_mode FROM settings WHERE id = 1"
        )
        row = cursor.fetchone()
    except sqlite3.OperationalError:
        return "consolidate"
    if not row or not row["global_consolidation_mode"]:
        return "consolidate"
    mode = row["global_consolidation_mode"]
    return mode if mode in ("consolidate", "separate") else "consolidate"


# =============================================================================
# Channel Number Allocation
# =============================================================================


def _get_all_used_channels(conn: Connection) -> set[int]:
    """Get all channel numbers used by enabled groups.

    Returns:
        Set of all used channel numbers across all groups.
    """
    cursor = conn.execute(
        """SELECT mc.channel_number
           FROM managed_channels mc
           LEFT JOIN event_epg_groups g ON mc.event_epg_group_id = g.id
           WHERE (g.enabled = 1 OR mc.event_epg_group_id IS NULL)
             AND mc.deleted_at IS NULL"""
    )

    used_set = set()
    for row in cursor.fetchall():
        if row["channel_number"]:
            try:
                used_set.add(int(float(row["channel_number"])))
            except (ValueError, TypeError):
                pass
    return used_set


def get_next_channel_number(
    conn: Connection,
    league: str | None = None,
    external_occupied: set[int] | None = None,
) -> int | None:
    """Get the next available channel number.

    Unified entry point for channel allocation. Delegates to AUTO or MANUAL
    mode based on global_channel_mode setting.

    Args:
        conn: Database connection
        league: League code for the event (used in MANUAL mode for per-league starts)
        external_occupied: Channel numbers occupied by non-Teamarr channels (#146)

    Returns:
        Next available channel number, or None if range exhausted
    """
    mode = get_global_channel_mode(conn)
    if mode == "manual":
        return _get_next_manual_channel(conn, league, external_occupied)
    return _get_next_auto_channel(conn, external_occupied)


def _get_next_auto_channel(
    conn: Connection,
    external_occupied: set[int] | None = None,
) -> int | None:
    """Get next available channel in AUTO mode.

    Finds the first unused channel number starting from range_start,
    considering all channels across all enabled groups and external
    Dispatcharr channels.

    Args:
        conn: Database connection
        external_occupied: Channel numbers occupied by non-Teamarr channels (#146)

    Returns:
        Next available channel number, or None if range exhausted
    """
    range_start, range_end = get_global_channel_range(conn)
    effective_end = range_end if range_end else MAX_CHANNEL

    used_set = _get_all_used_channels(conn)
    if external_occupied:
        used_set |= external_occupied

    next_num = range_start
    while next_num in used_set:
        next_num += 1
        if next_num > effective_end:
            logger.warning(
                "[CHANNEL_NUM] AUTO: No available channels (range %d-%d exhausted)",
                range_start, effective_end,
            )
            return None

    if next_num > MAX_CHANNEL:
        logger.warning("[CHANNEL_NUM] Channel number %d exceeds max %d", next_num, MAX_CHANNEL)
        return None

    return next_num


def _get_next_manual_channel(
    conn: Connection,
    league: str | None = None,
    external_occupied: set[int] | None = None,
) -> int | None:
    """Get next available channel in MANUAL mode.

    Uses per-league starting channel numbers. Leagues without configured
    starts fall back to global range (auto-assign from range_start).

    Args:
        conn: Database connection
        league: League code for the event
        external_occupied: Channel numbers occupied by non-Teamarr channels (#146)

    Returns:
        Next available channel number, or None if range exhausted
    """
    league_starts = get_league_channel_starts(conn)
    range_start, range_end = get_global_channel_range(conn)
    effective_end = range_end if range_end else MAX_CHANNEL

    # Determine starting number for this league
    start = league_starts.get(league) if league else None
    if start is None:
        # Fallback: auto-assign from global range
        start = range_start

    used_set = _get_all_used_channels(conn)
    if external_occupied:
        used_set |= external_occupied

    next_num = start
    while next_num in used_set:
        next_num += 1
        if next_num > effective_end:
            logger.warning(
                "[CHANNEL_NUM] MANUAL: No channels for league '%s' (from %d, end %d)",
                league, start, effective_end,
            )
            return None

    if next_num > MAX_CHANNEL:
        logger.warning("[CHANNEL_NUM] Channel number %d exceeds max %d", next_num, MAX_CHANNEL)
        return None

    return next_num


# =============================================================================
# Global Sorting & Reassignment
# =============================================================================


def get_all_channels_sorted(conn: Connection) -> list[dict]:
    """Get all active channels sorted by sport/league/time/event_id.

    Fetches all active channels from enabled groups and sorts them according
    to the sort_priorities table and event start times.

    Sort order:
    0. Priority team (followed teams float to the very top — channel_priority_teams)
    1. Sport priority (from channel_sort_priorities, lower = earlier)
    2. League priority (from channel_sort_priorities, lower = earlier)
    3. Event start time (earlier = earlier)
    4. Event ID (deterministic for same time)
    5. Main channel before keyword channels

    Returns:
        List of channel dicts with sort-relevant fields, ordered globally
    """
    from teamarr.database.priority_teams import get_priority_team_match_keys
    from teamarr.database.sort_priorities import get_all_sort_priorities

    # 1. Get sort priorities (normalize to lowercase for case-insensitive matching)
    priorities = get_all_sort_priorities(conn)
    sport_order = {p.sport.lower(): p.sort_priority for p in priorities if p.league_code is None}
    league_order = {
        (p.sport.lower(), p.league_code.lower() if p.league_code else None): p.sort_priority
        for p in priorities
        if p.league_code is not None
    }

    # Priority teams: (sport_lower, team_name_lower) keys; a channel floats to the
    # top if either its home or away team matches one (see channel_priority_teams).
    priority_keys = get_priority_team_match_keys(conn)

    # 2. Get all channels from enabled groups with event info
    cursor = conn.execute("""
        SELECT
            mc.id,
            mc.dispatcharr_channel_id,
            mc.channel_number,
            mc.channel_name,
            mc.event_epg_group_id,
            mc.primary_stream_id,
            mc.event_id,
            mc.sport,
            mc.league,
            mc.home_team,
            mc.away_team,
            mc.event_date,
            mc.exception_keyword,
            mc.created_at
        FROM managed_channels mc
        LEFT JOIN event_epg_groups g ON mc.event_epg_group_id = g.id
        WHERE (g.enabled = 1 OR mc.event_epg_group_id IS NULL)
          AND mc.deleted_at IS NULL
    """)

    channels = []
    for row in cursor.fetchall():
        channels.append(
            {
                "id": row["id"],
                "dispatcharr_channel_id": row["dispatcharr_channel_id"],
                "channel_number": row["channel_number"],
                "channel_name": row["channel_name"],
                "event_epg_group_id": row["event_epg_group_id"],
                "primary_stream_id": row["primary_stream_id"],
                "event_id": row["event_id"],
                "sport": row["sport"],
                "league": row["league"],
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "event_date": row["event_date"],
                "exception_keyword": row["exception_keyword"],
                "created_at": row["created_at"],
            }
        )

    # 3. Sort by: priority team → sport priority → league priority → time → event_id → keyword
    def sort_key(ch):
        sport = ch.get("sport") or ""
        league = ch.get("league") or ""
        event_date_str = ch.get("event_date")
        event_id = ch.get("event_id") or ""
        keyword = ch.get("exception_keyword") or ""

        sport_lower = sport.lower()
        league_lower = league.lower()

        # Priority-team tier (0 = priority, 1 = normal): match either team by name
        # within sport. Sorts first so followed teams lead, then normal ordering.
        home = (ch.get("home_team") or "").lower()
        away = (ch.get("away_team") or "").lower()
        is_priority = (sport_lower, home) in priority_keys or (sport_lower, away) in priority_keys
        priority_tier = 0 if is_priority else 1

        sport_pri = sport_order.get(sport_lower, 9999)
        league_pri = league_order.get((sport_lower, league_lower), 9999)

        # Parse event date
        if event_date_str:
            try:
                if "T" in str(event_date_str):
                    event_date = datetime.fromisoformat(str(event_date_str).replace("Z", "+00:00"))
                else:
                    event_date = datetime.strptime(str(event_date_str), "%Y-%m-%d %H:%M:%S")
                event_date = event_date.replace(tzinfo=None)
            except (ValueError, TypeError):
                event_date = datetime.max
        else:
            event_date = datetime.max

        # Main channel (no keyword) sorts before keyword channels
        keyword_sort = (0, "") if not keyword else (1, keyword)

        return (priority_tier, sport_pri, league_pri, event_date, str(event_id), keyword_sort)

    sorted_channels = sorted(channels, key=sort_key)

    logger.debug(
        "[CHANNEL_SORT] Global sort: %d channels, %d sport priorities, "
        "%d league priorities, %d priority teams",
        len(sorted_channels), len(sport_order), len(league_order), len(priority_keys),
    )

    return sorted_channels


def reassign_all_channels(
    conn: Connection,
    external_occupied: set[int] | None = None,
) -> dict:
    """Reassign all active channel numbers based on global mode.

    AUTO: Sequential numbers from range_start by sort priority order.
    MANUAL: Sequential within each league's configured range.

    Args:
        conn: Database connection
        external_occupied: Channel numbers occupied by non-Teamarr channels (#146)

    Returns:
        Dict with statistics: channels_processed, channels_moved, drift_details
    """
    mode = get_global_channel_mode(conn)
    if mode == "manual":
        return _reassign_manual(conn, external_occupied)
    return _reassign_auto(conn, external_occupied)


def _reassign_auto(
    conn: Connection,
    external_occupied: set[int] | None = None,
) -> dict:
    """Reassign all channels sequentially from range_start by sort order."""
    range_start, range_end = get_global_channel_range(conn)
    effective_end = range_end if range_end else MAX_CHANNEL
    ext_set = external_occupied or set()

    sorted_channels = get_all_channels_sorted(conn)

    if not sorted_channels:
        logger.info("[CHANNEL_SORT] No channels to reassign")
        return {"channels_processed": 0, "channels_moved": 0, "drift_details": []}

    channels_moved = 0
    drift_details = []

    next_num = range_start
    while next_num in ext_set:
        next_num += 1

    for ch in sorted_channels:
        old_num = ch["channel_number"]

        if next_num > effective_end:
            logger.warning(
                "[CHANNEL_SORT] AUTO reassign stopped at channel %d - range exhausted", ch["id"],
            )
            break

        if old_num != next_num:
            conn.execute(
                "UPDATE managed_channels SET channel_number = ? WHERE id = ?",
                (next_num, ch["id"]),
            )
            drift_details.append({
                "channel_id": ch["id"],
                "dispatcharr_channel_id": ch["dispatcharr_channel_id"],
                "channel_name": ch["channel_name"],
                "old_number": old_num,
                "new_number": next_num,
            })
            channels_moved += 1
            logger.debug(
                "[CHANNEL_NUM] '%s' moved #%s → #%d",
                ch["channel_name"], old_num, next_num,
            )

        next_num += 1
        while next_num in ext_set:
            next_num += 1

    logger.info(
        "[CHANNEL_SORT] AUTO reassign: %d channels processed, %d moved",
        len(sorted_channels), channels_moved,
    )

    return {
        "channels_processed": len(sorted_channels),
        "channels_moved": channels_moved,
        "drift_details": drift_details,
    }


def _reassign_manual(
    conn: Connection,
    external_occupied: set[int] | None = None,
) -> dict:
    """Reassign channels in MANUAL mode: sequential within each league's range."""
    league_starts = get_league_channel_starts(conn)
    range_start, range_end = get_global_channel_range(conn)
    effective_end = range_end if range_end else MAX_CHANNEL
    ext_set = external_occupied or set()

    sorted_channels = get_all_channels_sorted(conn)

    if not sorted_channels:
        logger.info("[CHANNEL_SORT] No channels to reassign (manual)")
        return {"channels_processed": 0, "channels_moved": 0, "drift_details": []}

    # Track next available number per league
    league_counters: dict[str, int] = {}
    channels_moved = 0
    drift_details = []

    for ch in sorted_channels:
        old_num = ch["channel_number"]
        league = (ch.get("league") or "").lower()

        if league not in league_counters:
            start = league_starts.get(league, range_start)
            # Skip external channels at the start
            while start in ext_set:
                start += 1
            league_counters[league] = start

        next_num = league_counters[league]
        while next_num in ext_set:
            next_num += 1

        if next_num > effective_end:
            logger.warning(
                "[CHANNEL_SORT] MANUAL reassign stopped for league '%s' - range exhausted", league,
            )
            continue

        if old_num != next_num:
            conn.execute(
                "UPDATE managed_channels SET channel_number = ? WHERE id = ?",
                (next_num, ch["id"]),
            )
            drift_details.append({
                "channel_id": ch["id"],
                "dispatcharr_channel_id": ch["dispatcharr_channel_id"],
                "channel_name": ch["channel_name"],
                "old_number": old_num,
                "new_number": next_num,
            })
            channels_moved += 1
            logger.debug(
                "[CHANNEL_NUM] '%s' moved #%s → #%d",
                ch["channel_name"], old_num, next_num,
            )

        league_counters[league] = next_num + 1

    logger.info(
        "[CHANNEL_SORT] MANUAL reassign: %d channels processed, %d moved",
        len(sorted_channels), channels_moved,
    )

    return {
        "channels_processed": len(sorted_channels),
        "channels_moved": channels_moved,
        "drift_details": drift_details,
    }
