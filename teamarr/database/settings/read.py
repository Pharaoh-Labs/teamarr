"""Settings read operations.

Query functions to fetch settings from the database.

All getters are registry-driven (see registry.py): one SELECT * of the
singleton settings row, then a generic column -> dataclass-field build per
group. Missing columns (un-reconciled DBs / partial test schemas) and NULLs
uniformly fall back to the dataclass defaults.
"""

from sqlite3 import Connection
from typing import Any

from .registry import GROUPS, GroupSpec
from .types import (
    AllSettings,
    BackupSettings,
    ChannelNumberingSettings,
    ChannelsDVRSettings,
    DispatcharrSettings,
    DisplaySettings,
    EmbySettings,
    EPGSettings,
    FeedSeparationSettings,
    JellyfinSettings,
    LifecycleSettings,
    SchedulerSettings,
    StreamFilterSettings,
    StreamOrderingSettings,
    TeamFilterSettings,
    UpdateCheckSettings,
)


def _fetch_row(conn: Connection):
    return conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()


def _build(group: GroupSpec, row) -> Any:
    """Build a settings dataclass from a DB row via the group's field specs."""
    keys = set(row.keys())
    return group.cls(
        **{
            fs.name: fs.from_db(row[fs.column] if fs.column in keys else None)
            for fs in group.fields
        }
    )


def _get_group(conn: Connection, name: str) -> Any:
    group = GROUPS[name]
    row = _fetch_row(conn)
    return group.cls() if row is None else _build(group, row)


def get_all_settings(conn: Connection) -> AllSettings:
    """Get all application settings.

    Args:
        conn: Database connection

    Returns:
        AllSettings object with all configuration
    """
    row = _fetch_row(conn)
    if not row:
        return AllSettings()

    keys = set(row.keys())

    def _scalar(column: str, fallback):
        value = row[column] if column in keys else None
        return value if value is not None else fallback

    return AllSettings(
        **{name: _build(group, row) for name, group in GROUPS.items()},
        epg_generation_counter=_scalar("epg_generation_counter", 0),
        schema_version=_scalar("schema_version", 2),
    )


def get_tsdb_api_key(conn: Connection) -> str | None:
    """Get the TSDB API key from settings.

    Args:
        conn: Database connection

    Returns:
        TSDB API key string or None if not set
    """
    cursor = conn.execute("SELECT tsdb_api_key FROM settings WHERE id = 1")
    row = cursor.fetchone()
    return row["tsdb_api_key"] if row else None


def get_dispatcharr_settings(conn: Connection) -> DispatcharrSettings:
    """Get Dispatcharr integration settings."""
    return _get_group(conn, "dispatcharr")


def get_scheduler_settings(conn: Connection) -> SchedulerSettings:
    """Get scheduler settings."""
    return _get_group(conn, "scheduler")


def get_lifecycle_settings(conn: Connection) -> LifecycleSettings:
    """Get channel lifecycle settings."""
    return _get_group(conn, "lifecycle")


def get_epg_settings(conn: Connection) -> EPGSettings:
    """Get EPG generation settings."""
    return _get_group(conn, "epg")


def get_display_settings(conn: Connection) -> DisplaySettings:
    """Get display settings."""
    return _get_group(conn, "display")


def get_stream_filter_settings(conn: Connection) -> StreamFilterSettings:
    """Get stream filtering settings (global defaults for event groups)."""
    return _get_group(conn, "stream_filter")


def get_team_filter_settings(conn: Connection) -> TeamFilterSettings:
    """Get default team filtering settings."""
    return _get_group(conn, "team_filter")


def get_channel_numbering_settings(conn: Connection) -> ChannelNumberingSettings:
    """Get channel numbering and consolidation settings."""
    return _get_group(conn, "channel_numbering")


def get_stream_ordering_settings(conn: Connection) -> StreamOrderingSettings:
    """Get stream ordering rules."""
    return _get_group(conn, "stream_ordering")


def get_update_check_settings(conn: Connection) -> UpdateCheckSettings:
    """Get update check settings."""
    return _get_group(conn, "update_check")


def get_feed_separation_settings(conn: Connection) -> FeedSeparationSettings:
    """Get feed separation settings."""
    return _get_group(conn, "feed_separation")


def get_backup_settings(conn: Connection) -> BackupSettings:
    """Get scheduled backup settings."""
    return _get_group(conn, "backup")


def get_emby_settings(conn: Connection) -> EmbySettings:
    """Get Emby integration settings."""
    return _get_group(conn, "emby")


def get_jellyfin_settings(conn: Connection) -> JellyfinSettings:
    """Get Jellyfin integration settings."""
    return _get_group(conn, "jellyfin")


def get_channelsdvr_settings(conn: Connection) -> ChannelsDVRSettings:
    """Get Channels DVR integration settings."""
    return _get_group(conn, "channelsdvr")
