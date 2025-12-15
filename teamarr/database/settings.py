"""Database operations for application settings.

Provides CRUD operations for the settings table (singleton row).
Settings are organized into logical groups for easier management.
"""

from dataclasses import dataclass, field
from sqlite3 import Connection


@dataclass
class DispatcharrSettings:
    """Dispatcharr integration settings."""

    enabled: bool = False
    url: str | None = None
    username: str | None = None
    password: str | None = None
    epg_id: int | None = None


@dataclass
class LifecycleSettings:
    """Channel lifecycle settings."""

    channel_create_timing: str = "same_day"
    channel_delete_timing: str = "day_after"
    channel_range_start: int = 101
    channel_range_end: int | None = None


@dataclass
class ReconciliationSettings:
    """Reconciliation settings."""

    reconcile_on_epg_generation: bool = True
    reconcile_on_startup: bool = True
    auto_fix_orphan_teamarr: bool = True
    auto_fix_orphan_dispatcharr: bool = False
    auto_fix_duplicates: bool = False
    default_duplicate_event_handling: str = "consolidate"
    channel_history_retention_days: int = 90


@dataclass
class SchedulerSettings:
    """Background scheduler settings."""

    enabled: bool = True
    interval_minutes: int = 15


@dataclass
class EPGSettings:
    """EPG generation settings."""

    team_schedule_days_ahead: int = 30
    event_match_days_ahead: int = 7
    epg_output_days_ahead: int = 14
    epg_lookback_hours: int = 6
    epg_timezone: str = "America/New_York"
    epg_output_path: str = "./teamarr.xml"
    include_final_events: bool = False
    midnight_crossover_mode: str = "postgame"
    cron_expression: str = "0 * * * *"


@dataclass
class DurationSettings:
    """Game duration settings (in hours)."""

    default: float = 3.0
    basketball: float = 3.0
    football: float = 3.5
    hockey: float = 3.0
    baseball: float = 3.5
    soccer: float = 2.5
    mma: float = 5.0
    rugby: float = 2.5
    boxing: float = 4.0
    tennis: float = 3.0
    golf: float = 6.0
    racing: float = 3.0
    cricket: float = 4.0


@dataclass
class DisplaySettings:
    """Display and formatting settings."""

    time_format: str = "12h"
    show_timezone: bool = True
    channel_id_format: str = "{team_name_pascal}.{league}"
    xmltv_generator_name: str = "Teamarr v2"
    xmltv_generator_url: str = "https://github.com/your-repo/teamarr"


@dataclass
class APISettings:
    """API behavior settings."""

    timeout: int = 10
    retry_count: int = 3
    soccer_cache_refresh_frequency: str = "weekly"
    team_cache_refresh_frequency: str = "weekly"


@dataclass
class AllSettings:
    """Complete application settings."""

    dispatcharr: DispatcharrSettings = field(default_factory=DispatcharrSettings)
    lifecycle: LifecycleSettings = field(default_factory=LifecycleSettings)
    reconciliation: ReconciliationSettings = field(default_factory=ReconciliationSettings)
    scheduler: SchedulerSettings = field(default_factory=SchedulerSettings)
    epg: EPGSettings = field(default_factory=EPGSettings)
    durations: DurationSettings = field(default_factory=DurationSettings)
    display: DisplaySettings = field(default_factory=DisplaySettings)
    api: APISettings = field(default_factory=APISettings)
    epg_generation_counter: int = 0
    schema_version: int = 2


# =============================================================================
# READ OPERATIONS
# =============================================================================


def get_all_settings(conn: Connection) -> AllSettings:
    """Get all application settings.

    Args:
        conn: Database connection

    Returns:
        AllSettings object with all configuration
    """
    cursor = conn.execute("SELECT * FROM settings WHERE id = 1")
    row = cursor.fetchone()

    if not row:
        return AllSettings()

    return AllSettings(
        dispatcharr=DispatcharrSettings(
            enabled=bool(row["dispatcharr_enabled"]),
            url=row["dispatcharr_url"],
            username=row["dispatcharr_username"],
            password=row["dispatcharr_password"],
            epg_id=row["dispatcharr_epg_id"],
        ),
        lifecycle=LifecycleSettings(
            channel_create_timing=row["channel_create_timing"] or "same_day",
            channel_delete_timing=row["channel_delete_timing"] or "day_after",
            channel_range_start=row["channel_range_start"] or 101,
            channel_range_end=row["channel_range_end"],
        ),
        reconciliation=ReconciliationSettings(
            reconcile_on_epg_generation=bool(row["reconcile_on_epg_generation"]),
            reconcile_on_startup=bool(row["reconcile_on_startup"]),
            auto_fix_orphan_teamarr=bool(row["auto_fix_orphan_teamarr"]),
            auto_fix_orphan_dispatcharr=bool(row["auto_fix_orphan_dispatcharr"]),
            auto_fix_duplicates=bool(row["auto_fix_duplicates"]),
            default_duplicate_event_handling=(
                row["default_duplicate_event_handling"] or "consolidate"
            ),
            channel_history_retention_days=row["channel_history_retention_days"] or 90,
        ),
        scheduler=SchedulerSettings(
            enabled=bool(row["scheduler_enabled"]),
            interval_minutes=row["scheduler_interval_minutes"] or 15,
        ),
        epg=EPGSettings(
            team_schedule_days_ahead=row["team_schedule_days_ahead"] or 30,
            event_match_days_ahead=row["event_match_days_ahead"] or 7,
            epg_output_days_ahead=row["epg_output_days_ahead"] or 14,
            epg_lookback_hours=row["epg_lookback_hours"] or 6,
            epg_timezone=row["epg_timezone"] or "America/New_York",
            epg_output_path=row["epg_output_path"] or "./teamarr.xml",
            include_final_events=bool(row["include_final_events"]),
            midnight_crossover_mode=row["midnight_crossover_mode"] or "postgame",
            cron_expression=row["cron_expression"] or "0 * * * *",
        ),
        durations=DurationSettings(
            default=row["duration_default"] or 3.0,
            basketball=row["duration_basketball"] or 3.0,
            football=row["duration_football"] or 3.5,
            hockey=row["duration_hockey"] or 3.0,
            baseball=row["duration_baseball"] or 3.5,
            soccer=row["duration_soccer"] or 2.5,
            mma=row["duration_mma"] or 5.0,
            rugby=row["duration_rugby"] or 2.5,
            boxing=row["duration_boxing"] or 4.0,
            tennis=row["duration_tennis"] or 3.0,
            golf=row["duration_golf"] or 6.0,
            racing=row["duration_racing"] or 3.0,
            cricket=row["duration_cricket"] or 4.0,
        ),
        display=DisplaySettings(
            time_format=row["time_format"] or "12h",
            show_timezone=bool(row["show_timezone"]),
            channel_id_format=row["channel_id_format"] or "{team_name_pascal}.{league}",
            xmltv_generator_name=row["xmltv_generator_name"] or "Teamarr v2",
            xmltv_generator_url=row["xmltv_generator_url"] or "",
        ),
        api=APISettings(
            timeout=row["api_timeout"] or 10,
            retry_count=row["api_retry_count"] or 3,
            soccer_cache_refresh_frequency=(row["soccer_cache_refresh_frequency"] or "weekly"),
            team_cache_refresh_frequency=row["team_cache_refresh_frequency"] or "weekly",
        ),
        epg_generation_counter=row["epg_generation_counter"] or 0,
        schema_version=row["schema_version"] or 2,
    )


def get_dispatcharr_settings(conn: Connection) -> DispatcharrSettings:
    """Get Dispatcharr integration settings.

    Args:
        conn: Database connection

    Returns:
        DispatcharrSettings object
    """
    cursor = conn.execute(
        """SELECT dispatcharr_enabled, dispatcharr_url, dispatcharr_username,
                  dispatcharr_password, dispatcharr_epg_id
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return DispatcharrSettings()

    return DispatcharrSettings(
        enabled=bool(row["dispatcharr_enabled"]),
        url=row["dispatcharr_url"],
        username=row["dispatcharr_username"],
        password=row["dispatcharr_password"],
        epg_id=row["dispatcharr_epg_id"],
    )


def get_scheduler_settings(conn: Connection) -> SchedulerSettings:
    """Get scheduler settings.

    Args:
        conn: Database connection

    Returns:
        SchedulerSettings object
    """
    cursor = conn.execute(
        "SELECT scheduler_enabled, scheduler_interval_minutes FROM settings WHERE id = 1"
    )
    row = cursor.fetchone()

    if not row:
        return SchedulerSettings()

    return SchedulerSettings(
        enabled=bool(row["scheduler_enabled"]),
        interval_minutes=row["scheduler_interval_minutes"] or 15,
    )


def get_lifecycle_settings(conn: Connection) -> LifecycleSettings:
    """Get channel lifecycle settings.

    Args:
        conn: Database connection

    Returns:
        LifecycleSettings object
    """
    cursor = conn.execute(
        """SELECT channel_create_timing, channel_delete_timing,
                  channel_range_start, channel_range_end
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return LifecycleSettings()

    return LifecycleSettings(
        channel_create_timing=row["channel_create_timing"] or "same_day",
        channel_delete_timing=row["channel_delete_timing"] or "day_after",
        channel_range_start=row["channel_range_start"] or 101,
        channel_range_end=row["channel_range_end"],
    )


def get_epg_settings(conn: Connection) -> EPGSettings:
    """Get EPG generation settings.

    Args:
        conn: Database connection

    Returns:
        EPGSettings object
    """
    cursor = conn.execute(
        """SELECT team_schedule_days_ahead, event_match_days_ahead,
                  epg_output_days_ahead, epg_lookback_hours, epg_timezone,
                  epg_output_path, include_final_events, midnight_crossover_mode,
                  cron_expression
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return EPGSettings()

    return EPGSettings(
        team_schedule_days_ahead=row["team_schedule_days_ahead"] or 30,
        event_match_days_ahead=row["event_match_days_ahead"] or 7,
        epg_output_days_ahead=row["epg_output_days_ahead"] or 14,
        epg_lookback_hours=row["epg_lookback_hours"] or 6,
        epg_timezone=row["epg_timezone"] or "America/New_York",
        epg_output_path=row["epg_output_path"] or "./teamarr.xml",
        include_final_events=bool(row["include_final_events"]),
        midnight_crossover_mode=row["midnight_crossover_mode"] or "postgame",
        cron_expression=row["cron_expression"] or "0 * * * *",
    )


# =============================================================================
# UPDATE OPERATIONS
# =============================================================================


def update_dispatcharr_settings(
    conn: Connection,
    enabled: bool | None = None,
    url: str | None = None,
    username: str | None = None,
    password: str | None = None,
    epg_id: int | None = None,
) -> bool:
    """Update Dispatcharr settings.

    Only updates fields that are explicitly provided (not None).

    Args:
        conn: Database connection
        enabled: Enable/disable integration
        url: Dispatcharr URL
        username: Username
        password: Password
        epg_id: EPG source ID in Dispatcharr

    Returns:
        True if updated
    """
    updates = []
    values = []

    if enabled is not None:
        updates.append("dispatcharr_enabled = ?")
        values.append(int(enabled))
    if url is not None:
        updates.append("dispatcharr_url = ?")
        values.append(url)
    if username is not None:
        updates.append("dispatcharr_username = ?")
        values.append(username)
    if password is not None:
        updates.append("dispatcharr_password = ?")
        values.append(password)
    if epg_id is not None:
        updates.append("dispatcharr_epg_id = ?")
        values.append(epg_id)

    if not updates:
        return False

    query = f"UPDATE settings SET {', '.join(updates)} WHERE id = 1"
    cursor = conn.execute(query, values)
    return cursor.rowcount > 0


def update_scheduler_settings(
    conn: Connection,
    enabled: bool | None = None,
    interval_minutes: int | None = None,
) -> bool:
    """Update scheduler settings.

    Args:
        conn: Database connection
        enabled: Enable/disable scheduler
        interval_minutes: Minutes between runs

    Returns:
        True if updated
    """
    updates = []
    values = []

    if enabled is not None:
        updates.append("scheduler_enabled = ?")
        values.append(int(enabled))
    if interval_minutes is not None:
        updates.append("scheduler_interval_minutes = ?")
        values.append(interval_minutes)

    if not updates:
        return False

    query = f"UPDATE settings SET {', '.join(updates)} WHERE id = 1"
    cursor = conn.execute(query, values)
    return cursor.rowcount > 0


def update_lifecycle_settings(
    conn: Connection,
    channel_create_timing: str | None = None,
    channel_delete_timing: str | None = None,
    channel_range_start: int | None = None,
    channel_range_end: int | None = None,
) -> bool:
    """Update channel lifecycle settings.

    Args:
        conn: Database connection
        channel_create_timing: When to create channels
        channel_delete_timing: When to delete channels
        channel_range_start: First auto-assigned channel number
        channel_range_end: Last auto-assigned channel number

    Returns:
        True if updated
    """
    updates = []
    values = []

    if channel_create_timing is not None:
        updates.append("channel_create_timing = ?")
        values.append(channel_create_timing)
    if channel_delete_timing is not None:
        updates.append("channel_delete_timing = ?")
        values.append(channel_delete_timing)
    if channel_range_start is not None:
        updates.append("channel_range_start = ?")
        values.append(channel_range_start)
    if channel_range_end is not None:
        updates.append("channel_range_end = ?")
        values.append(channel_range_end)

    if not updates:
        return False

    query = f"UPDATE settings SET {', '.join(updates)} WHERE id = 1"
    cursor = conn.execute(query, values)
    return cursor.rowcount > 0


def update_epg_settings(conn: Connection, **kwargs) -> bool:
    """Update EPG generation settings.

    Args:
        conn: Database connection
        **kwargs: EPG settings to update

    Returns:
        True if updated
    """
    field_mapping = {
        "team_schedule_days_ahead": "team_schedule_days_ahead",
        "event_match_days_ahead": "event_match_days_ahead",
        "epg_output_days_ahead": "epg_output_days_ahead",
        "epg_lookback_hours": "epg_lookback_hours",
        "epg_timezone": "epg_timezone",
        "epg_output_path": "epg_output_path",
        "include_final_events": "include_final_events",
        "midnight_crossover_mode": "midnight_crossover_mode",
        "cron_expression": "cron_expression",
    }

    updates = []
    values = []

    for key, column in field_mapping.items():
        if key in kwargs and kwargs[key] is not None:
            updates.append(f"{column} = ?")
            value = kwargs[key]
            if isinstance(value, bool):
                value = int(value)
            values.append(value)

    if not updates:
        return False

    query = f"UPDATE settings SET {', '.join(updates)} WHERE id = 1"
    cursor = conn.execute(query, values)
    return cursor.rowcount > 0


def update_reconciliation_settings(conn: Connection, **kwargs) -> bool:
    """Update reconciliation settings.

    Args:
        conn: Database connection
        **kwargs: Reconciliation settings to update

    Returns:
        True if updated
    """
    field_mapping = {
        "reconcile_on_epg_generation": "reconcile_on_epg_generation",
        "reconcile_on_startup": "reconcile_on_startup",
        "auto_fix_orphan_teamarr": "auto_fix_orphan_teamarr",
        "auto_fix_orphan_dispatcharr": "auto_fix_orphan_dispatcharr",
        "auto_fix_duplicates": "auto_fix_duplicates",
        "default_duplicate_event_handling": "default_duplicate_event_handling",
        "channel_history_retention_days": "channel_history_retention_days",
    }

    updates = []
    values = []

    for key, column in field_mapping.items():
        if key in kwargs and kwargs[key] is not None:
            updates.append(f"{column} = ?")
            value = kwargs[key]
            if isinstance(value, bool):
                value = int(value)
            values.append(value)

    if not updates:
        return False

    query = f"UPDATE settings SET {', '.join(updates)} WHERE id = 1"
    cursor = conn.execute(query, values)
    return cursor.rowcount > 0


def update_duration_settings(conn: Connection, **kwargs) -> bool:
    """Update game duration settings.

    Args:
        conn: Database connection
        **kwargs: Duration settings (default, basketball, football, etc.)

    Returns:
        True if updated
    """
    field_mapping = {
        "default": "duration_default",
        "basketball": "duration_basketball",
        "football": "duration_football",
        "hockey": "duration_hockey",
        "baseball": "duration_baseball",
        "soccer": "duration_soccer",
        "mma": "duration_mma",
        "rugby": "duration_rugby",
        "boxing": "duration_boxing",
        "tennis": "duration_tennis",
        "golf": "duration_golf",
        "racing": "duration_racing",
        "cricket": "duration_cricket",
    }

    updates = []
    values = []

    for key, column in field_mapping.items():
        if key in kwargs and kwargs[key] is not None:
            updates.append(f"{column} = ?")
            values.append(kwargs[key])

    if not updates:
        return False

    query = f"UPDATE settings SET {', '.join(updates)} WHERE id = 1"
    cursor = conn.execute(query, values)
    return cursor.rowcount > 0


def update_display_settings(conn: Connection, **kwargs) -> bool:
    """Update display/formatting settings.

    Args:
        conn: Database connection
        **kwargs: Display settings to update

    Returns:
        True if updated
    """
    field_mapping = {
        "time_format": "time_format",
        "show_timezone": "show_timezone",
        "channel_id_format": "channel_id_format",
        "xmltv_generator_name": "xmltv_generator_name",
        "xmltv_generator_url": "xmltv_generator_url",
    }

    updates = []
    values = []

    for key, column in field_mapping.items():
        if key in kwargs and kwargs[key] is not None:
            updates.append(f"{column} = ?")
            value = kwargs[key]
            if isinstance(value, bool):
                value = int(value)
            values.append(value)

    if not updates:
        return False

    query = f"UPDATE settings SET {', '.join(updates)} WHERE id = 1"
    cursor = conn.execute(query, values)
    return cursor.rowcount > 0


def increment_epg_generation_counter(conn: Connection) -> int:
    """Increment the EPG generation counter and return new value.

    Args:
        conn: Database connection

    Returns:
        New counter value
    """
    conn.execute(
        "UPDATE settings SET epg_generation_counter = epg_generation_counter + 1 WHERE id = 1"
    )
    cursor = conn.execute("SELECT epg_generation_counter FROM settings WHERE id = 1")
    row = cursor.fetchone()
    return row["epg_generation_counter"] if row else 1
