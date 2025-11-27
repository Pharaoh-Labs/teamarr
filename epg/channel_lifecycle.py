"""
Channel Lifecycle Manager for Event-based EPG

Handles automatic channel creation and deletion in Dispatcharr
based on matched streams and lifecycle settings.

EPG is injected directly via Dispatcharr's set-epg API, so tvg_id matching
is not needed for managed channels.
"""

import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def generate_channel_name(
    event: Dict,
    template: Optional[Dict] = None,
    template_engine = None,
    timezone: str = None
) -> str:
    """
    Generate channel name for an event.

    Uses template's channel_name field if available,
    otherwise falls back to "{away} @ {home}" format.

    Args:
        event: ESPN event data with home_team/away_team
        template: Optional event template with channel_name field
        template_engine: Optional template engine for variable resolution
        timezone: User's timezone for date/time formatting

    Returns:
        Channel name string
    """
    # If template has channel_name and we have an engine, use it
    if template and template.get('channel_name') and template_engine:
        from epg.event_template_engine import build_event_context
        ctx = build_event_context(event, {}, {}, timezone)
        return template_engine.resolve(template['channel_name'], ctx)

    # Default format: "Away @ Home"
    home = event.get('home_team', {})
    away = event.get('away_team', {})

    home_name = home.get('shortDisplayName') or home.get('name', 'Home')
    away_name = away.get('shortDisplayName') or away.get('name', 'Away')

    return f"{away_name} @ {home_name}"


def should_create_channel(
    event: Dict,
    create_timing: str,
    timezone: str
) -> Tuple[bool, str]:
    """
    Check if a channel should be created based on event date and timing setting.

    Args:
        event: ESPN event data with 'date' field
        create_timing: One of 'day_of', 'day_before', '2_days_before', 'week_before'
        timezone: Timezone for date comparison

    Returns:
        Tuple of (should_create: bool, reason: str)
    """
    event_date_str = event.get('date')
    if not event_date_str:
        return False, "No event date"

    try:
        # Parse event date
        if event_date_str.endswith('Z'):
            event_date_str = event_date_str[:-1] + '+00:00'
        event_dt = datetime.fromisoformat(event_date_str)

        # Convert to local timezone for date comparison
        tz = ZoneInfo(timezone)
        event_local = event_dt.astimezone(tz)
        event_date = event_local.date()

        # Get current date in same timezone
        now = datetime.now(tz)
        today = now.date()

        # Calculate threshold based on timing
        if create_timing == 'day_of':
            threshold_date = event_date
        elif create_timing == 'day_before':
            threshold_date = event_date - timedelta(days=1)
        elif create_timing == '2_days_before':
            threshold_date = event_date - timedelta(days=2)
        elif create_timing == 'week_before':
            threshold_date = event_date - timedelta(days=7)
        else:
            # Default to day_of
            threshold_date = event_date

        if today >= threshold_date:
            return True, f"Event on {event_date}, threshold {threshold_date}, today {today}"
        else:
            days_until = (threshold_date - today).days
            return False, f"Too early - {days_until} days until creation threshold"

    except Exception as e:
        logger.warning(f"Error checking create timing: {e}")
        return False, f"Error: {e}"


def calculate_delete_time(
    event: Dict,
    delete_timing: str,
    timezone: str
) -> Optional[datetime]:
    """
    Calculate when a channel should be deleted based on event and timing setting.

    Args:
        event: ESPN event data with 'date' field
        delete_timing: One of 'stream_removed', 'end_of_day', 'end_of_next_day', 'manual'
        timezone: Timezone for date calculation

    Returns:
        Datetime when channel should be deleted, or None for 'manual'/'stream_removed'
    """
    if delete_timing in ('manual', 'stream_removed'):
        return None

    event_date_str = event.get('date')
    if not event_date_str:
        return None

    try:
        # Parse event date
        if event_date_str.endswith('Z'):
            event_date_str = event_date_str[:-1] + '+00:00'
        event_dt = datetime.fromisoformat(event_date_str)

        # Convert to local timezone
        tz = ZoneInfo(timezone)
        event_local = event_dt.astimezone(tz)
        event_date = event_local.date()

        if delete_timing == 'end_of_day':
            # End of event day (midnight)
            delete_date = event_date + timedelta(days=1)
        elif delete_timing == 'end_of_next_day':
            # End of day after event
            delete_date = event_date + timedelta(days=2)
        else:
            return None

        # Return as datetime at midnight in the timezone
        return datetime.combine(delete_date, datetime.min.time()).replace(tzinfo=tz)

    except Exception as e:
        logger.warning(f"Error calculating delete time: {e}")
        return None


class ChannelLifecycleManager:
    """
    Manages channel creation and deletion for event-based EPG.

    Coordinates between:
    - Dispatcharr API (channel CRUD)
    - Local database (managed_channels tracking)
    - Event matching (which streams need channels)

    EPG is injected directly via set-epg API after channel creation.
    """

    def __init__(
        self,
        dispatcharr_url: str,
        dispatcharr_username: str,
        dispatcharr_password: str,
        timezone: str,
        epg_data_id: int = None
    ):
        """
        Initialize the lifecycle manager.

        Args:
            dispatcharr_url: Dispatcharr base URL
            dispatcharr_username: Dispatcharr username
            dispatcharr_password: Dispatcharr password
            epg_data_id: Teamarr's EPG source ID in Dispatcharr (for direct EPG injection)
            timezone: Default timezone for date calculations
        """
        from api.dispatcharr_client import ChannelManager

        self.channel_api = ChannelManager(
            dispatcharr_url,
            dispatcharr_username,
            dispatcharr_password
        )
        self.epg_data_id = epg_data_id
        self.timezone = timezone

    def process_matched_streams(
        self,
        matched_streams: List[Dict],
        group: Dict,
        template: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """
        Process matched streams and create/update channels as needed.

        Args:
            matched_streams: List of dicts with 'stream', 'teams', 'event' keys
            group: Event EPG group configuration
            template: Optional event template

        Returns:
            Dict with:
            - created: List of created channel records
            - skipped: List of skipped streams (with reasons)
            - errors: List of error messages
            - existing: List of already-existing channels
        """
        from database import (
            get_managed_channel_by_event,
            get_next_channel_number,
            create_managed_channel
        )

        results = {
            'created': [],
            'skipped': [],
            'errors': [],
            'existing': []
        }

        # Get lifecycle settings from group
        channel_start = group.get('channel_start')
        create_timing = group.get('channel_create_timing', 'day_of')
        delete_timing = group.get('channel_delete_timing', 'stream_removed')

        # Check if group has channel management enabled
        if not channel_start:
            logger.info(f"Group {group['id']} has no channel_start configured - skipping channel creation")
            results['skipped'] = [
                {'stream': m['stream']['name'], 'reason': 'No channel_start configured for group'}
                for m in matched_streams
            ]
            return results

        for matched in matched_streams:
            stream = matched['stream']
            event = matched['event']
            teams = matched.get('teams', {})

            espn_event_id = event.get('id')
            if not espn_event_id:
                results['errors'].append({
                    'stream': stream['name'],
                    'error': 'No ESPN event ID'
                })
                continue

            # Check if channel already exists for this event
            existing = get_managed_channel_by_event(espn_event_id, group['id'])
            if existing:
                results['existing'].append({
                    'stream': stream['name'],
                    'channel_id': existing['dispatcharr_channel_id'],
                    'channel_number': existing['channel_number']
                })
                continue

            # Check if we should create channel based on timing
            should_create, reason = should_create_channel(event, create_timing, self.timezone)
            if not should_create:
                results['skipped'].append({
                    'stream': stream['name'],
                    'reason': reason
                })
                continue

            # Get next channel number
            channel_number = get_next_channel_number(group['id'])
            if not channel_number:
                results['errors'].append({
                    'stream': stream['name'],
                    'error': 'Could not allocate channel number'
                })
                continue

            # Generate channel name
            channel_name = generate_channel_name(event, template, timezone=self.timezone)

            # Calculate scheduled delete time
            delete_at = calculate_delete_time(event, delete_timing, self.timezone)

            # Create channel in Dispatcharr (no tvg_id - EPG injected directly)
            create_result = self.channel_api.create_channel(
                name=channel_name,
                channel_number=channel_number,
                stream_ids=[stream['id']]
            )

            if not create_result.get('success'):
                results['errors'].append({
                    'stream': stream['name'],
                    'error': create_result.get('error', 'Unknown error')
                })
                continue

            dispatcharr_channel = create_result['channel']
            dispatcharr_channel_id = dispatcharr_channel['id']

            # Inject EPG directly via set-epg API
            if self.epg_data_id:
                epg_result = self.channel_api.set_channel_epg(
                    dispatcharr_channel_id,
                    self.epg_data_id
                )
                if not epg_result.get('success'):
                    logger.warning(
                        f"Failed to set EPG for channel {dispatcharr_channel_id}: "
                        f"{epg_result.get('error')}"
                    )

            # Track in database
            try:
                home_team = event.get('home_team', {}).get('name', '')
                away_team = event.get('away_team', {}).get('name', '')
                event_date = event.get('date', '')[:10] if event.get('date') else None

                managed_id = create_managed_channel(
                    event_epg_group_id=group['id'],
                    dispatcharr_channel_id=dispatcharr_channel_id,
                    dispatcharr_stream_id=stream['id'],
                    channel_number=channel_number,
                    channel_name=channel_name,
                    espn_event_id=espn_event_id,
                    event_date=event_date,
                    home_team=home_team,
                    away_team=away_team,
                    scheduled_delete_at=delete_at.isoformat() if delete_at else None
                )

                results['created'].append({
                    'stream': stream['name'],
                    'channel_id': dispatcharr_channel_id,
                    'channel_number': channel_number,
                    'channel_name': channel_name,
                    'managed_id': managed_id,
                    'scheduled_delete_at': delete_at.isoformat() if delete_at else None
                })

                logger.info(
                    f"Created channel {channel_number} '{channel_name}' "
                    f"for stream '{stream['name']}'"
                )

            except Exception as e:
                # Channel was created but tracking failed - try to delete it
                logger.error(f"Failed to track channel {dispatcharr_channel_id}: {e}")
                self.channel_api.delete_channel(dispatcharr_channel_id)
                results['errors'].append({
                    'stream': stream['name'],
                    'error': f'Database error: {e}'
                })

        return results

    def cleanup_deleted_streams(
        self,
        group: Dict,
        current_stream_ids: List[int]
    ) -> Dict[str, Any]:
        """
        Clean up channels for streams that no longer exist.

        Only applies if group's delete_timing is 'stream_removed'.

        Args:
            group: Event EPG group configuration
            current_stream_ids: List of current stream IDs from Dispatcharr

        Returns:
            Dict with deleted and error counts
        """
        from database import (
            get_managed_channels_for_group,
            mark_managed_channel_deleted
        )

        results = {
            'deleted': [],
            'errors': []
        }

        delete_timing = group.get('channel_delete_timing', 'stream_removed')
        if delete_timing != 'stream_removed':
            return results

        # Get all active managed channels for this group
        managed_channels = get_managed_channels_for_group(group['id'])
        current_ids_set = set(current_stream_ids)

        for channel in managed_channels:
            if channel['dispatcharr_stream_id'] not in current_ids_set:
                # Stream no longer exists - delete channel
                delete_result = self.channel_api.delete_channel(
                    channel['dispatcharr_channel_id']
                )

                if delete_result.get('success') or 'not found' in str(delete_result.get('error', '')).lower():
                    # Mark as deleted in database
                    mark_managed_channel_deleted(channel['id'])
                    results['deleted'].append({
                        'channel_id': channel['dispatcharr_channel_id'],
                        'channel_number': channel['channel_number'],
                        'channel_name': channel['channel_name']
                    })
                    logger.info(
                        f"Deleted channel {channel['channel_number']} "
                        f"'{channel['channel_name']}' - stream removed"
                    )
                else:
                    results['errors'].append({
                        'channel_id': channel['dispatcharr_channel_id'],
                        'error': delete_result.get('error')
                    })

        return results

    def process_scheduled_deletions(self) -> Dict[str, Any]:
        """
        Process channels that are past their scheduled deletion time.

        Should be called periodically (e.g., on each refresh or via cron).

        Returns:
            Dict with deleted and error counts
        """
        from database import (
            get_channels_pending_deletion,
            mark_managed_channel_deleted
        )

        results = {
            'deleted': [],
            'errors': []
        }

        pending = get_channels_pending_deletion()

        for channel in pending:
            delete_result = self.channel_api.delete_channel(
                channel['dispatcharr_channel_id']
            )

            if delete_result.get('success') or 'not found' in str(delete_result.get('error', '')).lower():
                mark_managed_channel_deleted(channel['id'])
                results['deleted'].append({
                    'channel_id': channel['dispatcharr_channel_id'],
                    'channel_number': channel['channel_number'],
                    'channel_name': channel['channel_name']
                })
                logger.info(
                    f"Deleted channel {channel['channel_number']} "
                    f"'{channel['channel_name']}' - scheduled deletion"
                )
            else:
                results['errors'].append({
                    'channel_id': channel['dispatcharr_channel_id'],
                    'error': delete_result.get('error')
                })

        return results


# =============================================================================
# Background Scheduler
# =============================================================================

_scheduler_thread = None
_scheduler_stop_event = None


def start_lifecycle_scheduler(interval_minutes: int = 15):
    """
    Start background scheduler for processing channel lifecycle.

    Runs periodically to:
    - Process scheduled deletions

    Args:
        interval_minutes: How often to run (default: 15 minutes)
    """
    import threading

    global _scheduler_thread, _scheduler_stop_event

    if _scheduler_thread and _scheduler_thread.is_alive():
        logger.warning("Lifecycle scheduler already running")
        return

    _scheduler_stop_event = threading.Event()

    def scheduler_loop():
        logger.info(f"Channel lifecycle scheduler started (interval: {interval_minutes} min)")

        while not _scheduler_stop_event.is_set():
            # Wait for interval (or stop event)
            if _scheduler_stop_event.wait(timeout=interval_minutes * 60):
                break  # Stop event was set

            try:
                logger.debug("Running scheduled lifecycle check...")
                manager = get_lifecycle_manager()
                if manager:
                    results = manager.process_scheduled_deletions()
                    if results['deleted']:
                        logger.info(f"Scheduler deleted {len(results['deleted'])} channels")
                    if results['errors']:
                        logger.warning(f"Scheduler had {len(results['errors'])} errors")
            except Exception as e:
                logger.error(f"Error in lifecycle scheduler: {e}")

        logger.info("Channel lifecycle scheduler stopped")

    _scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    _scheduler_thread.start()


def stop_lifecycle_scheduler():
    """Stop the background lifecycle scheduler."""
    global _scheduler_thread, _scheduler_stop_event

    if _scheduler_stop_event:
        _scheduler_stop_event.set()

    if _scheduler_thread:
        _scheduler_thread.join(timeout=5)
        _scheduler_thread = None
        _scheduler_stop_event = None
        logger.info("Lifecycle scheduler stopped")


def is_scheduler_running() -> bool:
    """Check if the lifecycle scheduler is running."""
    return _scheduler_thread is not None and _scheduler_thread.is_alive()


def get_lifecycle_manager() -> Optional[ChannelLifecycleManager]:
    """
    Get a ChannelLifecycleManager instance using settings from database.

    Returns:
        ChannelLifecycleManager or None if Dispatcharr not configured
    """
    from database import get_connection

    conn = get_connection()
    try:
        settings = dict(conn.execute("SELECT * FROM settings WHERE id = 1").fetchone())
    finally:
        conn.close()

    if not settings.get('dispatcharr_enabled'):
        return None

    url = settings.get('dispatcharr_url')
    username = settings.get('dispatcharr_username')
    password = settings.get('dispatcharr_password')
    timezone = settings.get('default_timezone', 'America/New_York')

    # EPG source ID in Dispatcharr (for direct EPG injection)
    epg_data_id = settings.get('dispatcharr_epg_id')

    if not all([url, username, password]):
        return None

    return ChannelLifecycleManager(
        url, username, password,
        timezone=timezone,
        epg_data_id=epg_data_id
    )
