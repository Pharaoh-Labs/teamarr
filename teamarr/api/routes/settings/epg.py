"""EPG settings endpoints."""

import logging

from fastapi import APIRouter

from teamarr.config import set_timezone
from teamarr.consumers.scheduler import (
    get_scheduler_status,
    start_lifecycle_scheduler,
    stop_lifecycle_scheduler,
)
from teamarr.database import get_db

from .models import EPGSettingsModel, to_model

logger = logging.getLogger(__name__)

router = APIRouter()


def _channel_source_group_names() -> dict[int, str]:
    """Dispatcharr channel group id -> name, to label new source rows.

    Empty on any failure: a row then gets a placeholder name, and the run-time
    sync renames it once Dispatcharr answers.
    """
    from teamarr.dispatcharr.factory import get_dispatcharr_connection

    try:
        dispatcharr = get_dispatcharr_connection(db_factory=get_db)
        if not dispatcharr:
            return {}
        return {g.id: g.name for g in dispatcharr.m3u.list_groups()}
    except Exception as e:
        logger.warning("[CHANNEL_SOURCE] Failed to list channel groups: %s", e)
        return {}


def _sync_channel_source_rows(before, after) -> None:
    """Create/enable/disable the channel-source rows the saved selection calls for (#986).

    The run-time sync does the same before every generation, but until then a
    newly picked Dispatcharr group had no source row, so it was missing from
    Sources and every picker that lists sources. Never raises: the settings
    are already saved, and the next run syncs the rows regardless.
    """
    selection = (after.epg_channel_source_enabled, sorted(after.epg_channel_source_groups))
    if selection == (before.epg_channel_source_enabled, sorted(before.epg_channel_source_groups)):
        return
    try:
        from teamarr.database.groups import ensure_channel_source_group

        enabled = after.epg_channel_source_enabled
        names = _channel_source_group_names() if enabled else None
        with get_db() as conn:
            ensure_channel_source_group(
                conn,
                enabled,
                selected_group_ids=list(after.epg_channel_source_groups),
                group_names=names,
            )
    except Exception:
        logger.exception("[CHANNEL_SOURCE] Failed to sync source rows on settings save")


@router.get("/settings/epg", response_model=EPGSettingsModel)
def get_epg_settings():
    """Get EPG generation settings."""
    from teamarr.database.settings import get_epg_settings

    with get_db() as conn:
        settings = get_epg_settings(conn)

    return to_model(EPGSettingsModel, settings)


@router.put("/settings/epg", response_model=EPGSettingsModel)
def update_epg_settings(update: EPGSettingsModel):
    """Update EPG generation settings."""
    from teamarr.database.settings import get_epg_settings, update_epg_settings

    # Check if cron expression is changing while scheduler is running
    scheduler_status = get_scheduler_status()
    scheduler_was_running = scheduler_status.get("running", False)
    cron_changed = scheduler_status.get("cron_expression") != update.cron_expression

    with get_db() as conn:
        before = get_epg_settings(conn)
        update_epg_settings(conn, **update.model_dump())
        after = get_epg_settings(conn)

    _sync_channel_source_rows(before, after)

    # Update cached timezone so new value is used immediately
    set_timezone(update.epg_timezone)

    # Restart scheduler if cron expression changed while it was running
    if scheduler_was_running and cron_changed:
        stop_lifecycle_scheduler()
        start_lifecycle_scheduler(get_db)

    with get_db() as conn:
        settings = get_epg_settings(conn)

    return to_model(EPGSettingsModel, settings)
