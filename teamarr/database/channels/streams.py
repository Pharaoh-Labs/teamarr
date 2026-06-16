"""Stream management operations for managed channels.

CRUD operations for managed_channel_streams table.
"""

import logging
from sqlite3 import Connection

from .types import ManagedChannelStream

logger = logging.getLogger(__name__)


def add_stream_to_channel(
    conn: Connection,
    managed_channel_id: int,
    dispatcharr_stream_id: int,
    stream_name: str | None = None,
    priority: int = 0,
    **kwargs,
) -> int:
    """Add a stream to a managed channel.

    Args:
        conn: Database connection
        managed_channel_id: Channel ID
        dispatcharr_stream_id: Stream ID in Dispatcharr
        stream_name: Stream display name
        priority: Stream priority (0 = primary)
        **kwargs: Additional fields

    Returns:
        ID of created stream record
    """
    columns = ["managed_channel_id", "dispatcharr_stream_id", "priority"]
    values = [managed_channel_id, dispatcharr_stream_id, priority]

    if stream_name:
        columns.append("stream_name")
        values.append(stream_name)

    allowed_fields = [
        "source_group_id",
        "source_group_type",
        "m3u_account_id",
        "m3u_account_name",
        "exception_keyword",
        "match_type",
        "match_method",  # how matched ('epg', 'fuzzy', …); drives the epg_match ordering rule
        "dispatcharr_channel_group",  # DP channel group; drives dispatcharr_group rule (ybt.3)
        "attach_at",   # time-windowed membership (183.5); None = full-life
        "detach_at",
    ]

    for field_name in allowed_fields:
        if field_name in kwargs and kwargs[field_name] is not None:
            columns.append(field_name)
            values.append(kwargs[field_name])

    placeholders = ", ".join(["?"] * len(values))
    column_str = ", ".join(columns)

    cursor = conn.execute(
        f"INSERT INTO managed_channel_streams ({column_str}) VALUES ({placeholders})",
        values,
    )
    stream_id = cursor.lastrowid
    logger.debug(
        "[ATTACHED] Stream %d to channel %d priority=%d",
        dispatcharr_stream_id,
        managed_channel_id,
        priority,
    )
    return stream_id


def remove_stream_from_channel(
    conn: Connection,
    managed_channel_id: int,
    dispatcharr_stream_id: int,
    reason: str | None = None,
) -> bool:
    """Soft-remove a stream from a channel.

    Args:
        conn: Database connection
        managed_channel_id: Channel ID
        dispatcharr_stream_id: Stream ID
        reason: Removal reason

    Returns:
        True if removed, False if not found
    """
    cursor = conn.execute(
        """UPDATE managed_channel_streams
           SET removed_at = datetime('now'),
               remove_reason = ?
           WHERE managed_channel_id = ?
             AND dispatcharr_stream_id = ?
             AND removed_at IS NULL""",
        (reason, managed_channel_id, dispatcharr_stream_id),
    )
    if cursor.rowcount > 0:
        logger.debug(
            "[DETACHED] Stream %d from channel %d reason=%s",
            dispatcharr_stream_id,
            managed_channel_id,
            reason,
        )
        return True
    return False


def get_channel_streams(
    conn: Connection,
    managed_channel_id: int,
    include_removed: bool = False,
) -> list[ManagedChannelStream]:
    """Get all streams for a channel.

    Args:
        conn: Database connection
        managed_channel_id: Channel ID
        include_removed: Whether to include removed streams

    Returns:
        List of ManagedChannelStream objects (ordered by priority)
    """
    if include_removed:
        cursor = conn.execute(
            """SELECT * FROM managed_channel_streams
               WHERE managed_channel_id = ?
               ORDER BY priority, added_at""",
            (managed_channel_id,),
        )
    else:
        cursor = conn.execute(
            """SELECT * FROM managed_channel_streams
               WHERE managed_channel_id = ? AND removed_at IS NULL
               ORDER BY priority, added_at""",
            (managed_channel_id,),
        )
    return [ManagedChannelStream.from_row(dict(row)) for row in cursor.fetchall()]


def stream_exists_on_channel(
    conn: Connection,
    managed_channel_id: int,
    dispatcharr_stream_id: int,
) -> bool:
    """Check if stream is attached to channel.

    Args:
        conn: Database connection
        managed_channel_id: Channel ID
        dispatcharr_stream_id: Stream ID

    Returns:
        True if stream exists on channel
    """
    cursor = conn.execute(
        """SELECT 1 FROM managed_channel_streams
           WHERE managed_channel_id = ?
             AND dispatcharr_stream_id = ?
             AND removed_at IS NULL""",
        (managed_channel_id, dispatcharr_stream_id),
    )
    return cursor.fetchone() is not None


def compute_stream_priority_from_rules(
    conn: Connection,
    stream_name: str | None = None,
    m3u_account_name: str | None = None,
    source_group_id: int | None = None,
) -> int:
    """Compute priority for a stream based on ordering rules.

    If rules are defined, computes priority based on first matching rule.
    If no rules or no match, returns 999 (sort to end).

    Args:
        conn: Database connection
        stream_name: Stream display name (for regex matching)
        m3u_account_name: M3U account name (for m3u type matching)
        source_group_id: Source group ID (for group type matching)

    Returns:
        Computed priority (lower = higher priority)
    """
    from teamarr.database.channels.types import ManagedChannelStream
    from teamarr.services.stream_ordering import get_stream_ordering_service

    ordering_service = get_stream_ordering_service(conn)
    if not ordering_service.rules:
        # No rules - use sequential ordering (will be assigned by get_next_stream_priority)
        return None  # type: ignore

    # Create a temporary stream object for matching
    temp_stream = ManagedChannelStream(
        id=0,
        managed_channel_id=0,
        dispatcharr_stream_id=0,
        stream_name=stream_name,
        m3u_account_name=m3u_account_name,
        source_group_id=source_group_id,
    )

    return ordering_service.compute_priority(temp_stream)


def get_next_stream_priority(conn: Connection, managed_channel_id: int) -> int:
    """Get the next available stream priority for a channel.

    Args:
        conn: Database connection
        managed_channel_id: Channel ID

    Returns:
        Next priority number (max + 1, or 0 if no streams)
    """
    cursor = conn.execute(
        """SELECT COALESCE(MAX(priority), -1) + 1 FROM managed_channel_streams
           WHERE managed_channel_id = ? AND removed_at IS NULL""",
        (managed_channel_id,),
    )
    return cursor.fetchone()[0]


def update_stream_name(
    conn: Connection,
    managed_channel_id: int,
    dispatcharr_stream_id: int,
    new_name: str,
) -> bool:
    """Update the stored stream name for an active stream record.

    Used when a stream's name changes but it's still matched to the same event
    (e.g., provider renamed the stream). Keeps the stream record in sync.

    Args:
        conn: Database connection
        managed_channel_id: Channel that owns the stream
        dispatcharr_stream_id: Stream ID in Dispatcharr
        new_name: New stream name to store

    Returns:
        True if updated, False if not found
    """
    cursor = conn.execute(
        """UPDATE managed_channel_streams
           SET stream_name = ?
           WHERE managed_channel_id = ? AND dispatcharr_stream_id = ? AND removed_at IS NULL""",
        (new_name, managed_channel_id, dispatcharr_stream_id),
    )
    if cursor.rowcount > 0:
        logger.debug(
            "Updated stream name for channel=%d stream=%d: %s",
            managed_channel_id,
            dispatcharr_stream_id,
            new_name,
        )
    return cursor.rowcount > 0


def update_stream_priority(
    conn: Connection,
    stream_db_id: int,
    new_priority: int,
) -> bool:
    """Update the priority of a stream.

    Args:
        conn: Database connection
        stream_db_id: Stream record ID in managed_channel_streams
        new_priority: New priority value

    Returns:
        True if updated, False if not found
    """
    cursor = conn.execute(
        """UPDATE managed_channel_streams
           SET priority = ?
           WHERE id = ?""",
        (new_priority, stream_db_id),
    )
    return cursor.rowcount > 0


def update_stream_window(
    conn: Connection,
    managed_channel_id: int,
    dispatcharr_stream_id: int,
    attach_at: str | None,
    detach_at: str | None,
) -> bool:
    """Refresh the time-window (attach_at/detach_at) of an attached stream.

    Used by epic teamarrv2-183.5 (bead teamarrv2-095): the window is recomputed
    every generation run from the fresh EPG program slot + current buffers, so a
    change to epg_stream_pre/post_buffer_minutes takes effect on already-attached
    streams instead of only at first attach. Targets the active (not removed) row.

    Returns True if a row was updated (i.e. the values actually changed), False
    otherwise.
    """
    cursor = conn.execute(
        """UPDATE managed_channel_streams
           SET attach_at = ?, detach_at = ?
           WHERE managed_channel_id = ?
             AND dispatcharr_stream_id = ?
             AND removed_at IS NULL
             AND (attach_at IS NOT ? OR detach_at IS NOT ?)""",
        (
            attach_at,
            detach_at,
            managed_channel_id,
            dispatcharr_stream_id,
            attach_at,
            detach_at,
        ),
    )
    if cursor.rowcount > 0:
        logger.debug(
            "[WINDOW] Stream %d on channel %d window -> attach=%s detach=%s",
            dispatcharr_stream_id,
            managed_channel_id,
            attach_at,
            detach_at,
        )
        return True
    return False


def reorder_channel_streams(
    conn: Connection,
    managed_channel_id: int,
) -> int:
    """Reorder streams on a channel based on stream ordering rules.

    Fetches stream ordering rules from settings and recomputes priority
    for all active streams on the channel.

    Args:
        conn: Database connection
        managed_channel_id: Channel ID

    Returns:
        Number of streams reordered
    """
    from teamarr.services.stream_ordering import get_stream_ordering_service

    # Get current streams
    streams = get_channel_streams(conn, managed_channel_id)
    if not streams:
        return 0

    # Get ordering service with rules
    ordering_service = get_stream_ordering_service(conn)
    if not ordering_service.rules:
        # No rules defined - skip reordering
        return 0

    # Compute priorities and update
    updated_count = 0
    for stream in streams:
        new_priority = ordering_service.compute_priority(stream)
        if stream.priority != new_priority:
            update_stream_priority(conn, stream.id, new_priority)
            updated_count += 1
            logger.debug(
                "[REORDER] Stream %d priority %d -> %d",
                stream.dispatcharr_stream_id,
                stream.priority,
                new_priority,
            )

    if updated_count > 0:
        logger.info(
            "[REORDER] Reordered %d/%d streams on channel %d",
            updated_count,
            len(streams),
            managed_channel_id,
        )

    return updated_count


def get_ordered_stream_ids(
    conn: Connection,
    managed_channel_id: int,
    now: str | None = None,
) -> list[int]:
    """Get the ACTIVE stream IDs for a channel in priority order.

    This is the set pushed to Dispatcharr. It honors time-windowed membership
    (epic teamarrv2-183.5): a stream is active when it has no window
    (attach_at IS NULL — full-life, the default) OR the current time is inside
    its window (attach_at <= now < detach_at). Out-of-window time-shared linear
    streams are excluded so they swap out of the channel until their next slot.

    Args:
        conn: Database connection
        managed_channel_id: Channel ID
        now: UTC "YYYY-MM-DD HH:MM:SS" timestamp for window gating. Defaults to
            SQLite datetime('now') (UTC). Pass explicitly for deterministic tests
            and to share one instant across a generation run.

    Returns:
        List of dispatcharr_stream_id values in priority order
    """
    now_expr = "datetime('now')" if now is None else "?"
    params: tuple = (
        (managed_channel_id,) if now is None else (managed_channel_id, now, now)
    )
    cursor = conn.execute(
        f"""SELECT dispatcharr_stream_id FROM managed_channel_streams
           WHERE managed_channel_id = ? AND removed_at IS NULL
             AND (attach_at IS NULL
                  OR (attach_at <= {now_expr} AND {now_expr} < detach_at))
           ORDER BY priority, added_at""",
        params,
    )
    return [row[0] for row in cursor.fetchall()]
