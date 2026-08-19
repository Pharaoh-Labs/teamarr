"""EPG settings endpoints."""

from fastapi import APIRouter

from teamarr.config import set_timezone
from teamarr.consumers.scheduler import (
    get_scheduler_status,
    start_lifecycle_scheduler,
    stop_lifecycle_scheduler,
)
from teamarr.database import get_db

from .models import EPGSettingsModel, to_model

router = APIRouter()


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
        update_epg_settings(conn, **update.model_dump())

    # Update cached timezone so new value is used immediately
    set_timezone(update.epg_timezone)

    # Restart scheduler if cron expression changed while it was running
    if scheduler_was_running and cron_changed:
        stop_lifecycle_scheduler()
        start_lifecycle_scheduler(get_db)

    with get_db() as conn:
        settings = get_epg_settings(conn)

    return to_model(EPGSettingsModel, settings)
