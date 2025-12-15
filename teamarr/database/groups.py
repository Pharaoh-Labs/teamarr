"""Database operations for event EPG groups.

Provides CRUD operations for the event_epg_groups table.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime
from sqlite3 import Connection


@dataclass
class EventEPGGroup:
    """Event EPG group configuration."""

    id: int
    name: str
    leagues: list[str]
    template_id: int | None = None
    channel_start_number: int | None = None
    channel_group_id: int | None = None
    stream_profile_id: int | None = None
    channel_profile_ids: list[int] = field(default_factory=list)
    create_timing: str = "same_day"
    delete_timing: str = "same_day"
    duplicate_event_handling: str = "consolidate"
    channel_assignment_mode: str = "auto"
    m3u_group_id: int | None = None
    m3u_group_name: str | None = None
    active: bool = True
    created_at: datetime | None = None
    updated_at: datetime | None = None


def _row_to_group(row) -> EventEPGGroup:
    """Convert a database row to EventEPGGroup."""
    leagues = json.loads(row["leagues"]) if row["leagues"] else []
    channel_profile_ids = []
    if row["channel_profile_ids"]:
        try:
            channel_profile_ids = json.loads(row["channel_profile_ids"])
        except (json.JSONDecodeError, TypeError):
            pass

    created_at = None
    if row["created_at"]:
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (ValueError, TypeError):
            pass

    updated_at = None
    if row["updated_at"]:
        try:
            updated_at = datetime.fromisoformat(row["updated_at"])
        except (ValueError, TypeError):
            pass

    return EventEPGGroup(
        id=row["id"],
        name=row["name"],
        leagues=leagues,
        template_id=row["template_id"],
        channel_start_number=row["channel_start_number"],
        channel_group_id=row["channel_group_id"],
        stream_profile_id=row["stream_profile_id"],
        channel_profile_ids=channel_profile_ids,
        create_timing=row["create_timing"] or "same_day",
        delete_timing=row["delete_timing"] or "same_day",
        duplicate_event_handling=row["duplicate_event_handling"] or "consolidate",
        channel_assignment_mode=row["channel_assignment_mode"] or "auto",
        m3u_group_id=row["m3u_group_id"],
        m3u_group_name=row["m3u_group_name"],
        active=bool(row["active"]),
        created_at=created_at,
        updated_at=updated_at,
    )


# =============================================================================
# READ OPERATIONS
# =============================================================================


def get_all_groups(conn: Connection, include_inactive: bool = False) -> list[EventEPGGroup]:
    """Get all event EPG groups.

    Args:
        conn: Database connection
        include_inactive: Include inactive groups

    Returns:
        List of EventEPGGroup objects
    """
    if include_inactive:
        cursor = conn.execute("SELECT * FROM event_epg_groups ORDER BY name")
    else:
        cursor = conn.execute("SELECT * FROM event_epg_groups WHERE active = 1 ORDER BY name")

    return [_row_to_group(row) for row in cursor.fetchall()]


def get_group(conn: Connection, group_id: int) -> EventEPGGroup | None:
    """Get a single event EPG group by ID.

    Args:
        conn: Database connection
        group_id: Group ID

    Returns:
        EventEPGGroup or None if not found
    """
    cursor = conn.execute("SELECT * FROM event_epg_groups WHERE id = ?", (group_id,))
    row = cursor.fetchone()
    return _row_to_group(row) if row else None


def get_group_by_name(conn: Connection, name: str) -> EventEPGGroup | None:
    """Get a single event EPG group by name.

    Args:
        conn: Database connection
        name: Group name

    Returns:
        EventEPGGroup or None if not found
    """
    cursor = conn.execute("SELECT * FROM event_epg_groups WHERE name = ?", (name,))
    row = cursor.fetchone()
    return _row_to_group(row) if row else None


def get_groups_for_league(conn: Connection, league: str) -> list[EventEPGGroup]:
    """Get all active groups that include a specific league.

    Args:
        conn: Database connection
        league: League code to search for

    Returns:
        List of EventEPGGroup objects that include the league
    """
    cursor = conn.execute("SELECT * FROM event_epg_groups WHERE active = 1 ORDER BY name")

    groups = []
    for row in cursor.fetchall():
        leagues = json.loads(row["leagues"]) if row["leagues"] else []
        if league in leagues:
            groups.append(_row_to_group(row))

    return groups


# =============================================================================
# CREATE OPERATIONS
# =============================================================================


def create_group(
    conn: Connection,
    name: str,
    leagues: list[str],
    template_id: int | None = None,
    channel_start_number: int | None = None,
    channel_group_id: int | None = None,
    stream_profile_id: int | None = None,
    channel_profile_ids: list[int] | None = None,
    create_timing: str = "same_day",
    delete_timing: str = "same_day",
    duplicate_event_handling: str = "consolidate",
    channel_assignment_mode: str = "auto",
    m3u_group_id: int | None = None,
    m3u_group_name: str | None = None,
    active: bool = True,
) -> int:
    """Create a new event EPG group.

    Args:
        conn: Database connection
        name: Unique group name
        leagues: List of league codes to scan
        template_id: Optional template ID
        channel_start_number: Starting channel number
        channel_group_id: Dispatcharr channel group ID
        stream_profile_id: Dispatcharr stream profile ID
        channel_profile_ids: List of channel profile IDs
        create_timing: When to create channels
        delete_timing: When to delete channels
        duplicate_event_handling: How to handle duplicate events
        channel_assignment_mode: 'auto' or 'manual'
        m3u_group_id: M3U group ID to scan
        m3u_group_name: M3U group name
        active: Whether group is active

    Returns:
        New group ID
    """
    cursor = conn.execute(
        """INSERT INTO event_epg_groups (
            name, leagues, template_id, channel_start_number,
            channel_group_id, stream_profile_id, channel_profile_ids,
            create_timing, delete_timing, duplicate_event_handling,
            channel_assignment_mode, m3u_group_id, m3u_group_name, active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            name,
            json.dumps(leagues),
            template_id,
            channel_start_number,
            channel_group_id,
            stream_profile_id,
            json.dumps(channel_profile_ids) if channel_profile_ids else None,
            create_timing,
            delete_timing,
            duplicate_event_handling,
            channel_assignment_mode,
            m3u_group_id,
            m3u_group_name,
            int(active),
        ),
    )
    return cursor.lastrowid


# =============================================================================
# UPDATE OPERATIONS
# =============================================================================


def update_group(
    conn: Connection,
    group_id: int,
    name: str | None = None,
    leagues: list[str] | None = None,
    template_id: int | None = None,
    channel_start_number: int | None = None,
    channel_group_id: int | None = None,
    stream_profile_id: int | None = None,
    channel_profile_ids: list[int] | None = None,
    create_timing: str | None = None,
    delete_timing: str | None = None,
    duplicate_event_handling: str | None = None,
    channel_assignment_mode: str | None = None,
    m3u_group_id: int | None = None,
    m3u_group_name: str | None = None,
    active: bool | None = None,
    clear_template: bool = False,
    clear_channel_start_number: bool = False,
    clear_channel_group_id: bool = False,
    clear_stream_profile_id: bool = False,
    clear_channel_profile_ids: bool = False,
    clear_m3u_group_id: bool = False,
    clear_m3u_group_name: bool = False,
) -> bool:
    """Update an event EPG group.

    Only updates fields that are explicitly provided (not None).
    Use clear_* flags to explicitly set fields to NULL.

    Args:
        conn: Database connection
        group_id: Group ID to update
        ... (field parameters)
        clear_*: Set corresponding field to NULL

    Returns:
        True if updated
    """
    updates = []
    values = []

    if name is not None:
        updates.append("name = ?")
        values.append(name)

    if leagues is not None:
        updates.append("leagues = ?")
        values.append(json.dumps(leagues))

    if template_id is not None:
        updates.append("template_id = ?")
        values.append(template_id)
    elif clear_template:
        updates.append("template_id = NULL")

    if channel_start_number is not None:
        updates.append("channel_start_number = ?")
        values.append(channel_start_number)
    elif clear_channel_start_number:
        updates.append("channel_start_number = NULL")

    if channel_group_id is not None:
        updates.append("channel_group_id = ?")
        values.append(channel_group_id)
    elif clear_channel_group_id:
        updates.append("channel_group_id = NULL")

    if stream_profile_id is not None:
        updates.append("stream_profile_id = ?")
        values.append(stream_profile_id)
    elif clear_stream_profile_id:
        updates.append("stream_profile_id = NULL")

    if channel_profile_ids is not None:
        updates.append("channel_profile_ids = ?")
        values.append(json.dumps(channel_profile_ids))
    elif clear_channel_profile_ids:
        updates.append("channel_profile_ids = NULL")

    if create_timing is not None:
        updates.append("create_timing = ?")
        values.append(create_timing)

    if delete_timing is not None:
        updates.append("delete_timing = ?")
        values.append(delete_timing)

    if duplicate_event_handling is not None:
        updates.append("duplicate_event_handling = ?")
        values.append(duplicate_event_handling)

    if channel_assignment_mode is not None:
        updates.append("channel_assignment_mode = ?")
        values.append(channel_assignment_mode)

    if m3u_group_id is not None:
        updates.append("m3u_group_id = ?")
        values.append(m3u_group_id)
    elif clear_m3u_group_id:
        updates.append("m3u_group_id = NULL")

    if m3u_group_name is not None:
        updates.append("m3u_group_name = ?")
        values.append(m3u_group_name)
    elif clear_m3u_group_name:
        updates.append("m3u_group_name = NULL")

    if active is not None:
        updates.append("active = ?")
        values.append(int(active))

    if not updates:
        return False

    values.append(group_id)
    query = f"UPDATE event_epg_groups SET {', '.join(updates)} WHERE id = ?"
    cursor = conn.execute(query, values)
    return cursor.rowcount > 0


def set_group_active(conn: Connection, group_id: int, active: bool) -> bool:
    """Set group active status.

    Args:
        conn: Database connection
        group_id: Group ID
        active: New active status

    Returns:
        True if updated
    """
    cursor = conn.execute(
        "UPDATE event_epg_groups SET active = ? WHERE id = ?", (int(active), group_id)
    )
    return cursor.rowcount > 0


# =============================================================================
# DELETE OPERATIONS
# =============================================================================


def delete_group(conn: Connection, group_id: int) -> bool:
    """Delete an event EPG group.

    Note: This will cascade delete all managed_channels for this group.

    Args:
        conn: Database connection
        group_id: Group ID to delete

    Returns:
        True if deleted
    """
    cursor = conn.execute("DELETE FROM event_epg_groups WHERE id = ?", (group_id,))
    return cursor.rowcount > 0


# =============================================================================
# STATS / HELPERS
# =============================================================================


def get_group_channel_count(conn: Connection, group_id: int) -> int:
    """Get count of managed channels for a group.

    Args:
        conn: Database connection
        group_id: Group ID

    Returns:
        Number of managed channels (active, not deleted)
    """
    cursor = conn.execute(
        """SELECT COUNT(*) as count FROM managed_channels
           WHERE event_epg_group_id = ? AND deleted_at IS NULL""",
        (group_id,),
    )
    row = cursor.fetchone()
    return row["count"] if row else 0


def get_group_stats(conn: Connection, group_id: int) -> dict:
    """Get statistics for a group.

    Args:
        conn: Database connection
        group_id: Group ID

    Returns:
        Dict with channel counts and status breakdown
    """
    cursor = conn.execute(
        """SELECT
            COUNT(*) as total,
            SUM(CASE WHEN deleted_at IS NULL THEN 1 ELSE 0 END) as active,
            SUM(CASE WHEN deleted_at IS NOT NULL THEN 1 ELSE 0 END) as deleted,
            SUM(CASE WHEN sync_status = 'pending' AND deleted_at IS NULL
                THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN sync_status = 'created' AND deleted_at IS NULL
                THEN 1 ELSE 0 END) as created,
            SUM(CASE WHEN sync_status = 'in_sync' AND deleted_at IS NULL
                THEN 1 ELSE 0 END) as in_sync,
            SUM(CASE WHEN sync_status = 'error' AND deleted_at IS NULL
                THEN 1 ELSE 0 END) as errors
        FROM managed_channels
        WHERE event_epg_group_id = ?""",
        (group_id,),
    )
    row = cursor.fetchone()

    if not row:
        return {"total": 0, "active": 0, "deleted": 0, "by_status": {}}

    return {
        "total": row["total"] or 0,
        "active": row["active"] or 0,
        "deleted": row["deleted"] or 0,
        "by_status": {
            "pending": row["pending"] or 0,
            "created": row["created"] or 0,
            "in_sync": row["in_sync"] or 0,
            "errors": row["errors"] or 0,
        },
    }


def get_all_group_stats(conn: Connection) -> dict[int, dict]:
    """Get statistics for all groups.

    Args:
        conn: Database connection

    Returns:
        Dict mapping group_id to stats dict
    """
    cursor = conn.execute(
        """SELECT
            event_epg_group_id,
            COUNT(*) as total,
            SUM(CASE WHEN deleted_at IS NULL THEN 1 ELSE 0 END) as active
        FROM managed_channels
        GROUP BY event_epg_group_id"""
    )

    stats = {}
    for row in cursor.fetchall():
        stats[row["event_epg_group_id"]] = {
            "total": row["total"] or 0,
            "active": row["active"] or 0,
        }

    return stats
