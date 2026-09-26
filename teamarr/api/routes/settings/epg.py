"""EPG settings endpoints."""

from croniter import croniter
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

    if update.scheduler_mode not in ("pre_match", "cron"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="scheduler_mode must be 'pre_match' or 'cron'",
        )
    if update.scheduler_mode == "cron":
        try:
            croniter(update.cron_expression)
        except (KeyError, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid cron expression: {e}",
            ) from None
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

    # Check if the scheduling mode/triggers are changing while running
    scheduler_status = get_scheduler_status()
    scheduler_was_running = scheduler_status.get("running", False)
    schedule_changed = (
        scheduler_status.get("mode") != update.scheduler_mode
        or scheduler_status.get("cron_expression") != update.cron_expression
        or scheduler_status.get("pre_match_lead_minutes") != update.pre_match_lead_minutes
        or scheduler_status.get("discovery_interval_hours") != update.epg_discovery_interval_hours
    )

    with get_db() as conn:
        update_epg_settings(conn, **update.model_dump())

    # Update cached timezone so new value is used immediately
    set_timezone(update.epg_timezone)

    # Restart scheduler if its mode/triggers changed while it was running
    if scheduler_was_running and schedule_changed:
        stop_lifecycle_scheduler()
        start_lifecycle_scheduler(get_db)

    with get_db() as conn:
        settings = get_epg_settings(conn)

    return to_model(EPGSettingsModel, settings)
