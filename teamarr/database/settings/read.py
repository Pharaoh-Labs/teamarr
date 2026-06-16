"""Settings read operations.

Query functions to fetch settings from the database.
"""

import json
from sqlite3 import Connection

from .types import (
    NO_VALUE_RULE_TYPES,
    AllSettings,
    APISettings,
    BackupSettings,
    ChannelNumberingSettings,
    ChannelsDVRSettings,
    DispatcharrSettings,
    DisplaySettings,
    DurationSettings,
    EmbySettings,
    EPGSettings,
    FeedSeparationSettings,
    JellyfinSettings,
    LifecycleSettings,
    ReconciliationSettings,
    SchedulerSettings,
    StreamFilterSettings,
    StreamOrderingRule,
    StreamOrderingSettings,
    TeamFilterSettings,
    UpdateCheckSettings,
)

# Single source of truth for defaults - the dataclass itself
_DISPLAY_DEFAULTS = DisplaySettings()


def _build_display_settings(row) -> DisplaySettings:
    """Build DisplaySettings from DB row, using dataclass defaults for NULL values."""
    d = _DISPLAY_DEFAULTS
    return DisplaySettings(
        time_format=row["time_format"] or d.time_format,
        show_timezone=bool(row["show_timezone"])
        if row["show_timezone"] is not None
        else d.show_timezone,
        channel_id_format=row["channel_id_format"] or d.channel_id_format,
        xmltv_generator_name=row["xmltv_generator_name"] or d.xmltv_generator_name,
        xmltv_generator_url=row["xmltv_generator_url"] or d.xmltv_generator_url,
        tsdb_api_key=row["tsdb_api_key"],
    )


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

    # Parse default_channel_profile_ids
    # None = all profiles, [] = no profiles, [1,2,...] = specific profiles
    default_profile_ids: list[int] | None = None
    if row["default_channel_profile_ids"]:
        try:
            parsed = json.loads(row["default_channel_profile_ids"])
            # json.loads("null") returns Python None, which is valid
            # json.loads("[]") returns Python [], which is valid
            # json.loads("[1,2]") returns Python [1,2], which is valid
            default_profile_ids = parsed
        except json.JSONDecodeError:
            default_profile_ids = None

    return AllSettings(
        dispatcharr=DispatcharrSettings(
            enabled=bool(row["dispatcharr_enabled"]),
            url=row["dispatcharr_url"],
            username=row["dispatcharr_username"],
            password=row["dispatcharr_password"],
            epg_id=row["dispatcharr_epg_id"],
            default_channel_profile_ids=default_profile_ids,
            default_stream_profile_id=row["default_stream_profile_id"],
            default_channel_group_id=row["default_channel_group_id"],
            default_channel_group_mode=row["default_channel_group_mode"] or "static",
            cleanup_unused_logos=bool(row["cleanup_unused_logos"])
            if row["cleanup_unused_logos"] is not None
            else False,
        ),
        lifecycle=LifecycleSettings(
            channel_create_timing=row["channel_create_timing"] or "same_day",
            channel_delete_timing=row["channel_delete_timing"] or "same_day",
            channel_pre_buffer_minutes=(
                row["channel_pre_buffer_minutes"]
                if row["channel_pre_buffer_minutes"] is not None
                else 60
            ),
            channel_post_buffer_minutes=(
                row["channel_post_buffer_minutes"]
                if row["channel_post_buffer_minutes"] is not None
                else 60
            ),
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
            channel_reset_enabled=bool(row["channel_reset_enabled"])
            if row["channel_reset_enabled"] is not None
            else False,
            channel_reset_cron=row["channel_reset_cron"],
        ),
        epg=EPGSettings(
            team_schedule_days_ahead=row["team_schedule_days_ahead"] or 30,
            event_match_days_ahead=row["event_match_days_ahead"] or 3,
            event_match_days_back=row["event_match_days_back"] or 7,
            epg_output_days_ahead=row["epg_output_days_ahead"] or 14,
            epg_lookback_hours=row["epg_lookback_hours"] or 6,
            epg_timezone=row["epg_timezone"] or "America/New_York",
            epg_output_path=row["epg_output_path"] or "./data/teamarr.xml",
            include_final_events=bool(row["include_final_events"]),
            midnight_crossover_mode=row["midnight_crossover_mode"] or "postgame",
            cron_expression=row["cron_expression"] or "0 * * * *",
            prepend_postponed_label=bool(row["prepend_postponed_label"])
            if row["prepend_postponed_label"] is not None
            else True,
            epg_xtream_fallback_enabled=bool(row["epg_xtream_fallback_enabled"])
            if "epg_xtream_fallback_enabled" in row.keys()
            else False,
            epg_xtream_cache_hours=(
                row["epg_xtream_cache_hours"]
                if "epg_xtream_cache_hours" in row.keys()
                else 24
            ) or 24,
            epg_channel_source_enabled=bool(row["epg_channel_source_enabled"])
            if "epg_channel_source_enabled" in row.keys()
            else False,
            epg_channel_source_groups=json.loads(
                row["epg_channel_source_groups"] or "[]"
            )
            if "epg_channel_source_groups" in row.keys()
            else [],
            epg_stream_pre_buffer_minutes=(
                row["epg_stream_pre_buffer_minutes"]
                if "epg_stream_pre_buffer_minutes" in row.keys()
                else 60
            ) or 60,
            epg_stream_post_buffer_minutes=(
                row["epg_stream_post_buffer_minutes"]
                if "epg_stream_post_buffer_minutes" in row.keys()
                else 60
            ) or 60,
            art_base_url=(
                row["art_base_url"] if "art_base_url" in row.keys() else ""
            ) or "",
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
            volleyball=row["duration_volleyball"] or 2.5,
        ),
        display=_build_display_settings(row),
        api=APISettings(
            timeout=row["api_timeout"] or 30,
            retry_count=row["api_retry_count"] or 5,
            soccer_cache_refresh_frequency=(row["soccer_cache_refresh_frequency"] or "weekly"),
            team_cache_refresh_frequency=row["team_cache_refresh_frequency"] or "weekly",
        ),
        stream_filter=StreamFilterSettings(
            require_event_pattern=bool(row["stream_filter_require_event_pattern"])
            if row["stream_filter_require_event_pattern"] is not None
            else True,
            include_patterns=json.loads(row["stream_filter_include_patterns"] or "[]"),
            exclude_patterns=json.loads(row["stream_filter_exclude_patterns"] or "[]"),
        ),
        team_filter=TeamFilterSettings(
            enabled=bool(row["team_filter_enabled"])
            if row["team_filter_enabled"] is not None
            else True,
            include_teams=json.loads(row["default_include_teams"])
            if row["default_include_teams"]
            else None,
            exclude_teams=json.loads(row["default_exclude_teams"])
            if row["default_exclude_teams"]
            else None,
            mode=row["default_team_filter_mode"] or "include",
            bypass_filter_for_playoffs=bool(row["default_bypass_filter_for_playoffs"])
            if "default_bypass_filter_for_playoffs" in row.keys()
            and row["default_bypass_filter_for_playoffs"] is not None
            else False,
        ),
        channel_numbering=_build_channel_numbering_settings(row),
        stream_ordering=StreamOrderingSettings(
            rules=_parse_stream_ordering_rules(row["stream_ordering_rules"])
        ),
        update_check=_build_update_check_settings(row),
        backup=_build_backup_settings(row),
        feed_separation=_build_feed_separation_settings(row),
        emby=_build_emby_settings(row),
        jellyfin=_build_jellyfin_settings(row),
        channelsdvr=_build_channelsdvr_settings(row),
        epg_generation_counter=row["epg_generation_counter"] or 0,
        schema_version=row["schema_version"] or 2,
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
    """Get Dispatcharr integration settings.

    Args:
        conn: Database connection

    Returns:
        DispatcharrSettings object
    """
    cursor = conn.execute(
        """SELECT dispatcharr_enabled, dispatcharr_url, dispatcharr_username,
                  dispatcharr_password, dispatcharr_epg_id, default_channel_profile_ids,
                  default_stream_profile_id, default_channel_group_id,
                  default_channel_group_mode, cleanup_unused_logos
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return DispatcharrSettings()

    # Parse JSON for default_channel_profile_ids
    # None = all profiles, [] = no profiles, [1,2,...] = specific profiles
    default_profile_ids: list[int] | None = None
    if row["default_channel_profile_ids"]:
        try:
            parsed = json.loads(row["default_channel_profile_ids"])
            default_profile_ids = parsed
        except json.JSONDecodeError:
            default_profile_ids = None

    return DispatcharrSettings(
        enabled=bool(row["dispatcharr_enabled"]),
        url=row["dispatcharr_url"],
        username=row["dispatcharr_username"],
        password=row["dispatcharr_password"],
        epg_id=row["dispatcharr_epg_id"],
        default_channel_profile_ids=default_profile_ids,
        default_stream_profile_id=row["default_stream_profile_id"],
        default_channel_group_id=row["default_channel_group_id"],
        default_channel_group_mode=row["default_channel_group_mode"] or "static",
        cleanup_unused_logos=bool(row["cleanup_unused_logos"])
        if row["cleanup_unused_logos"] is not None
        else False,
    )


def get_scheduler_settings(conn: Connection) -> SchedulerSettings:
    """Get scheduler settings.

    Args:
        conn: Database connection

    Returns:
        SchedulerSettings object
    """
    cursor = conn.execute(
        """SELECT scheduler_enabled, scheduler_interval_minutes,
                  channel_reset_enabled, channel_reset_cron
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return SchedulerSettings()

    return SchedulerSettings(
        enabled=bool(row["scheduler_enabled"]),
        interval_minutes=row["scheduler_interval_minutes"] or 15,
        channel_reset_enabled=bool(row["channel_reset_enabled"])
        if row["channel_reset_enabled"] is not None
        else False,
        channel_reset_cron=row["channel_reset_cron"],
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
                  channel_pre_buffer_minutes, channel_post_buffer_minutes,
                  channel_range_start, channel_range_end
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return LifecycleSettings()

    return LifecycleSettings(
        channel_create_timing=row["channel_create_timing"] or "same_day",
        channel_delete_timing=row["channel_delete_timing"] or "same_day",
        channel_pre_buffer_minutes=(
            row["channel_pre_buffer_minutes"]
            if row["channel_pre_buffer_minutes"] is not None
            else 60
        ),
        channel_post_buffer_minutes=(
            row["channel_post_buffer_minutes"]
            if row["channel_post_buffer_minutes"] is not None
            else 60
        ),
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
        """SELECT team_schedule_days_ahead, event_match_days_ahead, event_match_days_back,
                  epg_output_days_ahead, epg_lookback_hours, epg_timezone,
                  epg_output_path, include_final_events, midnight_crossover_mode,
                  cron_expression, prepend_postponed_label,
                  epg_xtream_fallback_enabled,
                  epg_xtream_cache_hours,
                  epg_channel_source_enabled, epg_channel_source_groups,
                  epg_stream_pre_buffer_minutes,
                  epg_stream_post_buffer_minutes,
                  art_base_url
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return EPGSettings()

    return EPGSettings(
        team_schedule_days_ahead=row["team_schedule_days_ahead"] or 30,
        event_match_days_ahead=row["event_match_days_ahead"] or 3,
        event_match_days_back=row["event_match_days_back"] or 7,
        epg_output_days_ahead=row["epg_output_days_ahead"] or 14,
        epg_lookback_hours=row["epg_lookback_hours"] or 6,
        epg_timezone=row["epg_timezone"] or "America/New_York",
        epg_output_path=row["epg_output_path"] or "./data/teamarr.xml",
        include_final_events=bool(row["include_final_events"]),
        midnight_crossover_mode=row["midnight_crossover_mode"] or "postgame",
        cron_expression=row["cron_expression"] or "0 * * * *",
        prepend_postponed_label=bool(row["prepend_postponed_label"])
        if row["prepend_postponed_label"] is not None
        else True,
        epg_xtream_fallback_enabled=bool(row["epg_xtream_fallback_enabled"]),
        epg_xtream_cache_hours=row["epg_xtream_cache_hours"] or 24,
        epg_channel_source_enabled=bool(row["epg_channel_source_enabled"]),
        epg_channel_source_groups=json.loads(row["epg_channel_source_groups"] or "[]"),
        epg_stream_pre_buffer_minutes=row["epg_stream_pre_buffer_minutes"] or 60,
        epg_stream_post_buffer_minutes=row["epg_stream_post_buffer_minutes"] or 60,
        art_base_url=row["art_base_url"] or "",
    )


def get_display_settings(conn: Connection) -> DisplaySettings:
    """Get display settings.

    Returns:
        DisplaySettings dataclass with time_format, show_timezone, etc.
    """
    cursor = conn.cursor()
    cursor.execute(
        """SELECT time_format, show_timezone, channel_id_format,
                  xmltv_generator_name, xmltv_generator_url, tsdb_api_key
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return DisplaySettings()

    return _build_display_settings(row)


def get_stream_filter_settings(conn: Connection) -> StreamFilterSettings:
    """Get stream filtering settings.

    Args:
        conn: Database connection

    Returns:
        StreamFilterSettings object with global filter configuration
    """
    cursor = conn.execute(
        """SELECT stream_filter_require_event_pattern,
                  stream_filter_include_patterns,
                  stream_filter_exclude_patterns
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return StreamFilterSettings()

    return StreamFilterSettings(
        require_event_pattern=bool(row["stream_filter_require_event_pattern"])
        if row["stream_filter_require_event_pattern"] is not None
        else True,
        include_patterns=json.loads(row["stream_filter_include_patterns"] or "[]"),
        exclude_patterns=json.loads(row["stream_filter_exclude_patterns"] or "[]"),
    )


def get_team_filter_settings(conn: Connection) -> TeamFilterSettings:
    """Get default team filtering settings.

    Args:
        conn: Database connection

    Returns:
        TeamFilterSettings object with global default team filter
    """
    cursor = conn.execute(
        """SELECT team_filter_enabled, default_include_teams, default_exclude_teams,
                  default_team_filter_mode, default_bypass_filter_for_playoffs
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return TeamFilterSettings()

    return TeamFilterSettings(
        enabled=bool(row["team_filter_enabled"])
        if row["team_filter_enabled"] is not None
        else True,
        include_teams=json.loads(row["default_include_teams"])
        if row["default_include_teams"]
        else None,
        exclude_teams=json.loads(row["default_exclude_teams"])
        if row["default_exclude_teams"]
        else None,
        mode=row["default_team_filter_mode"] or "include",
        bypass_filter_for_playoffs=bool(row["default_bypass_filter_for_playoffs"])
        if "default_bypass_filter_for_playoffs" in row.keys()
        and row["default_bypass_filter_for_playoffs"] is not None
        else False,
    )


def _build_channel_numbering_settings(row) -> ChannelNumberingSettings:
    """Build ChannelNumberingSettings from DB row."""
    league_starts = {}
    if row["league_channel_starts"]:
        try:
            parsed = json.loads(row["league_channel_starts"])
            if isinstance(parsed, dict):
                league_starts = {k: int(v) for k, v in parsed.items()}
        except (ValueError, TypeError, json.JSONDecodeError):
            pass

    return ChannelNumberingSettings(
        global_channel_mode=row["global_channel_mode"] or "auto",
        league_channel_starts=league_starts,
        global_consolidation_mode=row["global_consolidation_mode"] or "consolidate",
    )


def get_channel_numbering_settings(conn: Connection) -> ChannelNumberingSettings:
    """Get channel numbering and consolidation settings.

    Args:
        conn: Database connection

    Returns:
        ChannelNumberingSettings with global channel mode, league starts, consolidation
    """
    cursor = conn.execute(
        """SELECT global_channel_mode, league_channel_starts, global_consolidation_mode
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return ChannelNumberingSettings()

    return _build_channel_numbering_settings(row)


def _parse_stream_ordering_rules(rules_json: str | None) -> list[StreamOrderingRule]:
    """Parse stream ordering rules from JSON.

    Args:
        rules_json: JSON string of rules or None

    Returns:
        List of StreamOrderingRule objects
    """
    if not rules_json:
        return []

    try:
        rules_data = json.loads(rules_json)
        if not isinstance(rules_data, list):
            return []

        return [
            StreamOrderingRule(
                type=rule.get("type", "m3u"),
                value=rule.get("value", ""),
                priority=rule.get("priority", 99),
            )
            for rule in rules_data
            if isinstance(rule, dict)
            and rule.get("type")
            and (rule.get("type") in NO_VALUE_RULE_TYPES or rule.get("value"))
        ]
    except json.JSONDecodeError:
        return []


def get_stream_ordering_settings(conn: Connection) -> StreamOrderingSettings:
    """Get stream ordering rules.

    Args:
        conn: Database connection

    Returns:
        StreamOrderingSettings object with rules list
    """
    cursor = conn.execute("SELECT stream_ordering_rules FROM settings WHERE id = 1")
    row = cursor.fetchone()

    if not row:
        return StreamOrderingSettings()

    return StreamOrderingSettings(rules=_parse_stream_ordering_rules(row["stream_ordering_rules"]))


# Single source of truth for update check defaults
_UPDATE_CHECK_DEFAULTS = UpdateCheckSettings()


def _build_update_check_settings(row) -> UpdateCheckSettings:
    """Build UpdateCheckSettings from DB row, using dataclass defaults for NULL values."""
    d = _UPDATE_CHECK_DEFAULTS
    return UpdateCheckSettings(
        enabled=bool(row["update_check_enabled"])
        if row["update_check_enabled"] is not None
        else d.enabled,
        notify_stable=bool(row["update_notify_stable"])
        if row["update_notify_stable"] is not None
        else d.notify_stable,
        notify_dev=bool(row["update_notify_dev"])
        if row["update_notify_dev"] is not None
        else d.notify_dev,
        github_owner=row["update_github_owner"] or d.github_owner,
        github_repo=row["update_github_repo"] or d.github_repo,
        dev_branch=row["update_dev_branch"] or d.dev_branch,
        auto_detect_branch=bool(row["update_auto_detect_branch"])
        if row["update_auto_detect_branch"] is not None
        else d.auto_detect_branch,
    )


def get_update_check_settings(conn: Connection) -> UpdateCheckSettings:
    """Get update check settings.

    Args:
        conn: Database connection

    Returns:
        UpdateCheckSettings object with update notification configuration
    """
    cursor = conn.execute(
        """SELECT update_check_enabled, update_notify_stable, update_notify_dev,
                  update_github_owner, update_github_repo, update_dev_branch,
                  update_auto_detect_branch
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return UpdateCheckSettings()

    return _build_update_check_settings(row)


# Single source of truth for feed separation defaults
_FEED_SEPARATION_DEFAULTS = FeedSeparationSettings()


def _build_feed_separation_settings(row) -> FeedSeparationSettings:
    """Build FeedSeparationSettings from DB row, using dataclass defaults for NULL values."""
    d = _FEED_SEPARATION_DEFAULTS

    # Parse JSON arrays for home/away terms
    home_terms = d.home_terms
    if "feed_home_terms" in row.keys() and row["feed_home_terms"]:
        try:
            parsed = json.loads(row["feed_home_terms"])
            if isinstance(parsed, list):
                home_terms = parsed
        except json.JSONDecodeError:
            pass

    away_terms = d.away_terms
    if "feed_away_terms" in row.keys() and row["feed_away_terms"]:
        try:
            parsed = json.loads(row["feed_away_terms"])
            if isinstance(parsed, list):
                away_terms = parsed
        except json.JSONDecodeError:
            pass

    return FeedSeparationSettings(
        enabled=bool(row["feed_separation_enabled"])
        if "feed_separation_enabled" in row.keys()
        and row["feed_separation_enabled"] is not None
        else d.enabled,
        home_terms=home_terms,
        away_terms=away_terms,
        detect_team_names=bool(row["feed_detect_team_names"])
        if "feed_detect_team_names" in row.keys()
        and row["feed_detect_team_names"] is not None
        else d.detect_team_names,
        label_style=row["feed_label_style"] or d.label_style
        if "feed_label_style" in row.keys()
        else d.label_style,
    )


def get_feed_separation_settings(conn: Connection) -> FeedSeparationSettings:
    """Get feed separation settings.

    Args:
        conn: Database connection

    Returns:
        FeedSeparationSettings object with feed detection configuration
    """
    cursor = conn.execute(
        """SELECT feed_separation_enabled, feed_home_terms, feed_away_terms,
                  feed_detect_team_names, feed_label_style
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return FeedSeparationSettings()

    return _build_feed_separation_settings(row)


# Single source of truth for backup settings defaults
_BACKUP_DEFAULTS = BackupSettings()


def _build_backup_settings(row) -> BackupSettings:
    """Build BackupSettings from DB row, using dataclass defaults for NULL values."""
    d = _BACKUP_DEFAULTS
    return BackupSettings(
        enabled=bool(row["scheduled_backup_enabled"])
        if row["scheduled_backup_enabled"] is not None
        else d.enabled,
        cron=row["scheduled_backup_cron"] or d.cron,
        max_count=row["scheduled_backup_max_count"]
        if row["scheduled_backup_max_count"] is not None
        else d.max_count,
        path=row["scheduled_backup_path"] or d.path,
    )


def get_backup_settings(conn: Connection) -> BackupSettings:
    """Get scheduled backup settings.

    Args:
        conn: Database connection

    Returns:
        BackupSettings object with backup configuration
    """
    cursor = conn.execute(
        """SELECT scheduled_backup_enabled, scheduled_backup_cron,
                  scheduled_backup_max_count, scheduled_backup_path
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return BackupSettings()

    return _build_backup_settings(row)


# Single source of truth for Emby settings defaults
_EMBY_DEFAULTS = EmbySettings()


def _build_emby_settings(row) -> EmbySettings:
    """Build EmbySettings from DB row, using dataclass defaults for NULL."""
    d = _EMBY_DEFAULTS
    return EmbySettings(
        enabled=bool(row["emby_enabled"])
        if "emby_enabled" in row.keys()
        and row["emby_enabled"] is not None
        else d.enabled,
        url=row["emby_url"]
        if "emby_url" in row.keys()
        else d.url,
        username=row["emby_username"]
        if "emby_username" in row.keys()
        else d.username,
        password=row["emby_password"]
        if "emby_password" in row.keys()
        else d.password,
        api_key=row["emby_api_key"]
        if "emby_api_key" in row.keys()
        else d.api_key,
    )


def get_emby_settings(conn: Connection) -> EmbySettings:
    """Get Emby integration settings.

    Args:
        conn: Database connection

    Returns:
        EmbySettings object with Emby configuration
    """
    cursor = conn.execute(
        """SELECT emby_enabled, emby_url, emby_username, emby_password,
                  emby_api_key
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return EmbySettings()

    return _build_emby_settings(row)


_JELLYFIN_DEFAULTS = JellyfinSettings()


def _build_jellyfin_settings(row) -> JellyfinSettings:
    """Build JellyfinSettings from DB row, using dataclass defaults for NULL."""
    d = _JELLYFIN_DEFAULTS
    return JellyfinSettings(
        enabled=bool(row["jellyfin_enabled"])
        if "jellyfin_enabled" in row.keys()
        and row["jellyfin_enabled"] is not None
        else d.enabled,
        url=row["jellyfin_url"]
        if "jellyfin_url" in row.keys()
        else d.url,
        username=row["jellyfin_username"]
        if "jellyfin_username" in row.keys()
        else d.username,
        password=row["jellyfin_password"]
        if "jellyfin_password" in row.keys()
        else d.password,
        api_key=row["jellyfin_api_key"]
        if "jellyfin_api_key" in row.keys()
        else d.api_key,
    )


def get_jellyfin_settings(conn: Connection) -> JellyfinSettings:
    """Get Jellyfin integration settings.

    Args:
        conn: Database connection

    Returns:
        JellyfinSettings object with Jellyfin configuration
    """
    cursor = conn.execute(
        """SELECT jellyfin_enabled, jellyfin_url, jellyfin_username,
                  jellyfin_password, jellyfin_api_key
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return JellyfinSettings()

    return _build_jellyfin_settings(row)


_CHANNELSDVR_DEFAULTS = ChannelsDVRSettings()


def _build_channelsdvr_settings(row) -> ChannelsDVRSettings:
    """Build ChannelsDVRSettings from DB row, using dataclass defaults for NULL."""
    d = _CHANNELSDVR_DEFAULTS
    return ChannelsDVRSettings(
        enabled=bool(row["channelsdvr_enabled"])
        if "channelsdvr_enabled" in row.keys()
        and row["channelsdvr_enabled"] is not None
        else d.enabled,
        url=row["channelsdvr_url"]
        if "channelsdvr_url" in row.keys()
        else d.url,
        source_name=row["channelsdvr_source_name"]
        if "channelsdvr_source_name" in row.keys()
        else d.source_name,
        lineup_id=row["channelsdvr_lineup_id"]
        if "channelsdvr_lineup_id" in row.keys()
        else d.lineup_id,
    )


def get_channelsdvr_settings(conn: Connection) -> ChannelsDVRSettings:
    """Get Channels DVR integration settings.

    Args:
        conn: Database connection

    Returns:
        ChannelsDVRSettings object with Channels DVR configuration
    """
    cursor = conn.execute(
        """SELECT channelsdvr_enabled, channelsdvr_url, channelsdvr_source_name,
                  channelsdvr_lineup_id
           FROM settings WHERE id = 1"""
    )
    row = cursor.fetchone()

    if not row:
        return ChannelsDVRSettings()

    return _build_channelsdvr_settings(row)
