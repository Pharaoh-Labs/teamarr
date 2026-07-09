"""Managed channel CRUD operations.

Create, Read, Update, Delete operations for managed_channels table.
"""

import json
import logging
from sqlite3 import Connection

from teamarr.utilities.tz import now_user

from .types import ManagedChannel

logger = logging.getLogger(__name__)

# Cache for column existence checks (cleared on module reload)
_column_cache: dict[str, bool] = {}


def _has_column(conn: Connection, table: str, column: str) -> bool:
    """Check if a column exists in a table (cached per session)."""
    key = f"{table}.{column}"
    if key not in _column_cache:
        cols = {
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        _column_cache[key] = column in cols
    return _column_cache[key]


def create_managed_channel(
    conn: Connection,
    event_epg_group_id: int | None,
    event_id: str,
    event_provider: str,
    tvg_id: str,
    channel_name: str,
    **kwargs,
) -> int:
    """Create a managed channel record.

    Simple INSERT - V1 parity. No reactivation logic needed since tvg_id
    is no longer UNIQUE. Soft-deleted records naturally coexist with new ones.

    Args:
        conn: Database connection
        event_epg_group_id: Source group ID (provenance — which group
            supplied the first stream). May be None.
        event_id: Event ID from provider
        event_provider: Provider name (espn, tsdb, etc.)
        tvg_id: XMLTV TVG ID
        channel_name: Display name
        **kwargs: Additional fields (channel_number, logo_url, etc.)

    Returns:
        ID of created record
    """
    # Build column list and values
    columns = [
        "event_id",
        "event_provider",
        "tvg_id",
        "channel_name",
    ]
    values: list = [event_id, event_provider, tvg_id, channel_name]

    # event_epg_group_id is optional (provenance, not ownership)
    if event_epg_group_id is not None:
        columns.append("event_epg_group_id")
        values.append(event_epg_group_id)

    # Add optional fields
    allowed_fields = [
        "channel_number",
        "logo_url",
        "dispatcharr_channel_id",
        "dispatcharr_uuid",
        "dispatcharr_logo_id",
        "channel_group_id",
        "channel_profile_ids",
        "primary_stream_id",
        "exception_keyword",
        "feed_team_id",
        "home_team",
        "home_team_abbrev",
        "home_team_logo",
        "away_team",
        "away_team_abbrev",
        "away_team_logo",
        "event_date",
        "event_name",
        "league",
        "sport",
        "venue",
        "broadcast",
        "scheduled_delete_at",
        "sync_status",
    ]

    for field_name in allowed_fields:
        if field_name in kwargs and kwargs[field_name] is not None:
            # Skip feed_team_id if column doesn't exist yet (migration v69)
            if field_name == "feed_team_id" and not _has_column(
                conn, "managed_channels", "feed_team_id"
            ):
                continue
            columns.append(field_name)
            value = kwargs[field_name]
            # Serialize lists/dicts to JSON
            if isinstance(value, (list, dict)):
                value = json.dumps(value)
            values.append(value)

    placeholders = ", ".join(["?"] * len(values))
    column_str = ", ".join(columns)

    cursor = conn.execute(
        f"INSERT INTO managed_channels ({column_str}) VALUES ({placeholders})",
        values,
    )
    channel_id = cursor.lastrowid
    assert channel_id is not None  # just-inserted row always has a rowid
    logger.info(
        "[CREATED] Managed channel id=%d name=%s event=%s", channel_id, channel_name, event_id
    )
    return channel_id


def get_managed_channel(conn: Connection, channel_id: int) -> ManagedChannel | None:
    """Get a managed channel by ID.

    Args:
        conn: Database connection
        channel_id: Channel ID

    Returns:
        ManagedChannel or None if not found
    """
    cursor = conn.execute("SELECT * FROM managed_channels WHERE id = ?", (channel_id,))
    row = cursor.fetchone()
    if not row:
        return None
    return ManagedChannel.from_row(dict(row))


def get_managed_channel_by_tvg_id(conn: Connection, tvg_id: str) -> ManagedChannel | None:
    """Get a managed channel by TVG ID.

    Args:
        conn: Database connection
        tvg_id: TVG ID

    Returns:
        ManagedChannel or None if not found
    """
    cursor = conn.execute(
        "SELECT * FROM managed_channels WHERE tvg_id = ? AND deleted_at IS NULL",
        (tvg_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return ManagedChannel.from_row(dict(row))


def get_managed_channel_by_event(
    conn: Connection,
    event_id: str,
    event_provider: str,
    group_id: int | None = None,
) -> ManagedChannel | None:
    """Get a managed channel by event ID.

    Args:
        conn: Database connection
        event_id: Event ID
        event_provider: Provider name
        group_id: Optional group filter

    Returns:
        ManagedChannel or None if not found
    """
    if group_id:
        cursor = conn.execute(
            """SELECT * FROM managed_channels
               WHERE event_id = ? AND event_provider = ?
                 AND event_epg_group_id = ? AND deleted_at IS NULL""",
            (event_id, event_provider, group_id),
        )
    else:
        cursor = conn.execute(
            """SELECT * FROM managed_channels
               WHERE event_id = ? AND event_provider = ? AND deleted_at IS NULL""",
            (event_id, event_provider),
        )
    row = cursor.fetchone()
    if not row:
        return None
    return ManagedChannel.from_row(dict(row))


def get_managed_channel_by_dispatcharr_id(
    conn: Connection,
    dispatcharr_channel_id: int,
) -> ManagedChannel | None:
    """Get a managed channel by Dispatcharr channel ID.

    Args:
        conn: Database connection
        dispatcharr_channel_id: Dispatcharr channel ID

    Returns:
        ManagedChannel or None if not found
    """
    cursor = conn.execute(
        "SELECT * FROM managed_channels WHERE dispatcharr_channel_id = ?",
        (dispatcharr_channel_id,),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return ManagedChannel.from_row(dict(row))


def get_managed_channels_for_group(
    conn: Connection,
    group_id: int,
    include_deleted: bool = False,
) -> list[ManagedChannel]:
    """Get managed channels related to a specific source group.

    Returns channels where either:
    - The channel was created by this group (event_epg_group_id = group_id), OR
    - The channel has active streams sourced from this group (source_group_id = group_id)

    This allows each group to validate its own streams even on channels
    created by other groups (e.g., consolidated channels with cross-group streams).

    Args:
        conn: Database connection
        group_id: Source group ID to filter by
        include_deleted: Whether to include deleted channels

    Returns:
        List of ManagedChannel objects (deduplicated)
    """
    deleted_clause = "" if include_deleted else "AND mc.deleted_at IS NULL"
    cursor = conn.execute(
        f"""SELECT DISTINCT mc.* FROM managed_channels mc
            LEFT JOIN managed_channel_streams mcs
                ON mc.id = mcs.managed_channel_id AND mcs.removed_at IS NULL
            WHERE (mc.event_epg_group_id = ? OR mcs.source_group_id = ?)
            {deleted_clause}
            ORDER BY mc.channel_number""",
        (group_id, group_id),
    )
    return [ManagedChannel.from_row(dict(row)) for row in cursor.fetchall()]


def get_channels_pending_deletion(conn: Connection) -> list[ManagedChannel]:
    """Get channels past their scheduled delete time.

    Uses Python datetime comparison to handle ISO format with timezone properly,
    since SQLite's datetime('now') returns different format than stored values.

    Args:
        conn: Database connection

    Returns:
        List of ManagedChannel objects ready for deletion
    """

    from dateutil import parser


    # Get all active channels with scheduled_delete_at
    cursor = conn.execute(
        """SELECT * FROM managed_channels
           WHERE scheduled_delete_at IS NOT NULL
             AND deleted_at IS NULL
           ORDER BY scheduled_delete_at""",
    )

    now = now_user()
    pending = []

    for row in cursor.fetchall():
        channel = ManagedChannel.from_row(dict(row))
        if channel.scheduled_delete_at:
            try:
                # Parse the stored delete time (ISO format with timezone)
                delete_time = parser.parse(str(channel.scheduled_delete_at))
                if now >= delete_time:
                    pending.append(channel)
            except (ValueError, TypeError):
                # If parsing fails, skip this channel
                pass

    return pending


def get_all_managed_channels(
    conn: Connection,
    include_deleted: bool = False,
    sport: str | None = None,
    league: str | None = None,
) -> list[ManagedChannel]:
    """Get all managed channels, optionally filtered by sport/league.

    Args:
        conn: Database connection
        include_deleted: Whether to include deleted channels
        sport: Optional sport filter
        league: Optional league filter

    Returns:
        List of ManagedChannel objects
    """
    conditions = []
    params: list = []

    if not include_deleted:
        conditions.append("deleted_at IS NULL")
    if sport:
        conditions.append("sport = ?")
        params.append(sport)
    if league:
        conditions.append("league = ?")
        params.append(league)

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    sql = f"SELECT * FROM managed_channels{where} ORDER BY sport, league, channel_number"
    cursor = conn.execute(sql, params)
    return [ManagedChannel.from_row(dict(row)) for row in cursor.fetchall()]


def count_active_managed_channels(conn: Connection) -> int:
    """Count managed channels that are not deleted."""
    return conn.execute(
        "SELECT COUNT(*) FROM managed_channels WHERE deleted_at IS NULL"
    ).fetchone()[0]


def update_managed_channel(conn: Connection, channel_id: int, data: dict) -> bool:
    """Update managed channel fields.

    Args:
        conn: Database connection
        channel_id: Channel ID to update
        data: Fields to update

    Returns:
        True if updated, False if not found
    """
    if not data:
        return False

    # Serialize JSON fields
    for key in ["channel_profile_ids"]:
        if key in data and isinstance(data[key], (list, dict)):
            data[key] = json.dumps(data[key])

    set_clause = ", ".join(f"{k} = ?" for k in data.keys())
    values = list(data.values()) + [channel_id]

    cursor = conn.execute(
        f"UPDATE managed_channels SET {set_clause} WHERE id = ?",
        values,
    )
    if cursor.rowcount > 0:
        logger.debug("[UPDATED] Managed channel id=%d fields=%s", channel_id, list(data.keys()))
        return True
    return False


def mark_channel_deleted(
    conn: Connection,
    channel_id: int,
    reason: str | None = None,
) -> bool:
    """Mark a channel as deleted (soft delete).

    Args:
        conn: Database connection
        channel_id: Channel ID
        reason: Delete reason

    Returns:
        True if updated, False if not found
    """
    cursor = conn.execute(
        """UPDATE managed_channels
           SET deleted_at = datetime('now'),
               delete_reason = ?
           WHERE id = ?""",
        (reason, channel_id),
    )
    if cursor.rowcount > 0:
        logger.info("[DELETED] Managed channel id=%d reason=%s", channel_id, reason)
        return True
    return False


def mark_all_channels_deleted(conn: Connection) -> tuple[int, int]:
    """Mark all active managed channels as deleted (soft delete).

    Used by channel reset operations.

    Args:
        conn: Database connection

    Returns:
        Tuple of (count_before, rows_updated)
    """
    cursor = conn.execute("SELECT COUNT(*) FROM managed_channels WHERE deleted_at IS NULL")
    count_before = cursor.fetchone()[0]

    cursor = conn.execute(
        """UPDATE managed_channels
           SET deleted_at = CURRENT_TIMESTAMP
           WHERE deleted_at IS NULL"""
    )
    rows_updated = cursor.rowcount
    conn.commit()

    logger.info(
        "Reset: marked %d managed_channels as deleted (had %d active records before)",
        rows_updated,
        count_before,
    )
    return count_before, rows_updated


def find_existing_channel(
    conn: Connection,
    event_id: str,
    event_provider: str,
    exception_keyword: str | None = None,
    stream_id: int | None = None,
    mode: str = "consolidate",
    feed_team_id: str | None = None,
) -> ManagedChannel | None:
    """Find existing channel by event identity (event-scoped).

    Channel identity: (event_id, event_provider, exception_keyword,
    feed_team_id, primary_stream_id).
    Searches across ALL source groups — channels are owned by events, not groups.

    Args:
        conn: Database connection
        event_id: Event ID
        event_provider: Provider name
        exception_keyword: Exception keyword for separate consolidation
        stream_id: Stream ID (for 'separate' mode)
        mode: Duplicate handling mode (consolidate, separate, ignore)
        feed_team_id: Feed team ID for feed separation (HOME/AWAY channels)

    Returns:
        Existing ManagedChannel or None
    """
    if mode == "separate":
        # In separate mode, each stream gets its own channel
        if stream_id:
            cursor = conn.execute(
                """SELECT * FROM managed_channels
                   WHERE event_id = ?
                     AND event_provider = ?
                     AND primary_stream_id = ?
                     AND deleted_at IS NULL""",
                (event_id, event_provider, stream_id),
            )
            row = cursor.fetchone()
            if row:
                return ManagedChannel.from_row(dict(row))
        return None

    elif mode == "ignore":
        # In ignore mode, first stream wins - just check if any channel exists
        cursor = conn.execute(
            """SELECT * FROM managed_channels
               WHERE event_id = ?
                 AND event_provider = ?
                 AND deleted_at IS NULL
               LIMIT 1""",
            (event_id, event_provider),
        )
        row = cursor.fetchone()
        if row:
            return ManagedChannel.from_row(dict(row))
        return None

    else:  # consolidate (default)
        # In consolidate mode, look for channel with same keyword + feed_team
        # Build WHERE clause dynamically based on nullable fields
        conditions = ["event_id = ?", "event_provider = ?", "deleted_at IS NULL"]
        params: list = [event_id, event_provider]

        if exception_keyword:
            conditions.append("exception_keyword = ?")
            params.append(exception_keyword)
        else:
            conditions.append("exception_keyword IS NULL")

        # feed_team_id column may not exist yet (migration v69)
        # Check before adding to avoid OperationalError
        has_feed_col = _has_column(conn, "managed_channels", "feed_team_id")
        if has_feed_col:
            if feed_team_id:
                conditions.append("feed_team_id = ?")
                params.append(feed_team_id)
            else:
                conditions.append("feed_team_id IS NULL")

        where = " AND ".join(conditions)
        cursor = conn.execute(
            f"SELECT * FROM managed_channels WHERE {where}",
            params,
        )
        row = cursor.fetchone()
        if row:
            return ManagedChannel.from_row(dict(row))
        return None




def find_any_channel_for_event(
    conn: Connection,
    event_id: str,
    event_provider: str,
    exclude_group_id: int | None = None,
    exception_keyword: str | None = None,
    any_keyword: bool = False,
) -> ManagedChannel | None:
    """Find any existing channel for an event across all source groups.

    Checks if a channel already exists for this event, regardless of which
    group supplied the initial stream. Used during stream processing to
    consolidate streams onto existing event channels.

    Args:
        conn: Database connection
        event_id: Event ID
        event_provider: Provider name
        exclude_group_id: Optional source group ID to exclude from search
        exception_keyword: If set, match channels with this keyword
        any_keyword: If True, match any channel regardless of keyword

    Returns:
        First matching ManagedChannel or None if not found
    """
    params: list = [event_id, event_provider]

    sql = """SELECT * FROM managed_channels
             WHERE event_id = ?
               AND event_provider = ?
               AND deleted_at IS NULL"""

    if exclude_group_id:
        sql += " AND event_epg_group_id != ?"
        params.append(exclude_group_id)

    # Keyword filtering
    if not any_keyword:
        if exception_keyword:
            sql += " AND exception_keyword = ?"
            params.append(exception_keyword)
        else:
            sql += " AND (exception_keyword IS NULL OR exception_keyword = '')"
    # any_keyword=True: no keyword filter, match any channel

    sql += " ORDER BY created_at ASC LIMIT 1"

    cursor = conn.execute(sql, params)
    row = cursor.fetchone()
    if row:
        return ManagedChannel.from_row(dict(row))
    return None
