"""EPG settings endpoints."""

from fastapi import APIRouter, HTTPException, status

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

    if update.pre_match_lead_minutes < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pre_match_lead_minutes must be 0 or greater",
        )
    if update.epg_discovery_interval_hours < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="epg_discovery_interval_hours must be at least 1",
        )

    # Check if the scheduling triggers are changing while the scheduler is running
    scheduler_status = get_scheduler_status()
    scheduler_was_running = scheduler_status.get("running", False)
    triggers_changed = (
        scheduler_status.get("pre_match_lead_minutes") != update.pre_match_lead_minutes
        or scheduler_status.get("discovery_interval_hours") != update.epg_discovery_interval_hours
    )

    with get_db() as conn:
        update_epg_settings(conn, **update.model_dump())

    # Update cached timezone so new value is used immediately
    set_timezone(update.epg_timezone)

    # Restart scheduler if its triggers changed while it was running
    if scheduler_was_running and triggers_changed:
        stop_lifecycle_scheduler()
        start_lifecycle_scheduler(get_db)

    with get_db() as conn:
        settings = get_epg_settings(conn)

    return to_model(EPGSettingsModel, settings)
