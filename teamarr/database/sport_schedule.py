"""Per-sport pre-match lead time overrides for the EPG scheduler.

Manages the sport_schedule_overrides table. A sport with no row here uses
epg_settings.pre_match_lead_minutes (the global default) — see
teamarr/consumers/scheduler.py for where these are read.
"""

import logging
from dataclasses import dataclass
from sqlite3 import Connection

from teamarr.core.sports import get_sport_display_names_from_db

logger = logging.getLogger(__name__)


@dataclass
class SportScheduleOverride:
    """A per-sport pre-match lead time override."""

    sport: str
    pre_match_lead_minutes: int
    display_name: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


def get_sport_lead_overrides(conn: Connection) -> dict[str, int]:
    """Get all overrides as a {sport: pre_match_lead_minutes} lookup.

    This is the shape the scheduler needs — cheap to query fresh each time
    since the table is tiny (at most one row per sport).
    """
    cursor = conn.execute("SELECT sport, pre_match_lead_minutes FROM sport_schedule_overrides")
    return {row["sport"]: row["pre_match_lead_minutes"] for row in cursor.fetchall()}


def get_sport_lead_overrides_with_display(conn: Connection) -> list[SportScheduleOverride]:
    """Get all overrides with display names, for the settings UI."""
    cursor = conn.execute("""
        SELECT sport, pre_match_lead_minutes, created_at, updated_at
        FROM sport_schedule_overrides
        ORDER BY sport ASC
    """)
    display_names = get_sport_display_names_from_db(conn)

    return [
        SportScheduleOverride(
            sport=row["sport"],
            pre_match_lead_minutes=row["pre_match_lead_minutes"],
            display_name=display_names.get(row["sport"], row["sport"].title()),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
        for row in cursor.fetchall()
    ]


def upsert_sport_lead_override(
    conn: Connection,
    sport: str,
    pre_match_lead_minutes: int,
    *,
    commit: bool = True,
) -> bool:
    """Insert or update a sport's pre-match lead time override.

    Args:
        conn: Database connection
        sport: Sport code (e.g., 'football', 'mma')
        pre_match_lead_minutes: Minutes before this sport's matches to
            trigger generation
        commit: Whether to commit the transaction (default True). Pass False
            when called as part of a larger transaction.

    Returns:
        True if inserted/updated successfully
    """
    try:
        conn.execute(
            """
            INSERT INTO sport_schedule_overrides (sport, pre_match_lead_minutes)
            VALUES (?, ?)
            ON CONFLICT(sport) DO UPDATE SET
                pre_match_lead_minutes = excluded.pre_match_lead_minutes,
                updated_at = CURRENT_TIMESTAMP
            """,
            (sport, pre_match_lead_minutes),
        )
        if commit:
            conn.commit()
        logger.info(
            "[SPORT_SCHEDULE] Set lead time: sport=%s, minutes=%d",
            sport,
            pre_match_lead_minutes,
        )
        return True
    except Exception as e:
        logger.error("[SPORT_SCHEDULE] Failed to upsert override: %s", e)
        return False


def delete_sport_lead_override(conn: Connection, sport: str, *, commit: bool = True) -> bool:
    """Remove a sport's override, reverting it to the global default.

    Returns:
        True if deleted (or didn't exist)
    """
    try:
        conn.execute("DELETE FROM sport_schedule_overrides WHERE sport = ?", (sport,))
        if commit:
            conn.commit()
        logger.info("[SPORT_SCHEDULE] Removed override for sport=%s", sport)
        return True
    except Exception as e:
        logger.error("[SPORT_SCHEDULE] Failed to delete override: %s", e)
        return False
