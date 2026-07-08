"""Lifecycle and scheduler settings endpoints."""

from fastapi import APIRouter, HTTPException, status

from teamarr.consumers.scheduler import (
    restart_scheduler_sub_task,
    start_lifecycle_scheduler,
    stop_lifecycle_scheduler,
)
from teamarr.database import get_db
from teamarr.dispatcharr import get_dispatcharr_client
from teamarr.services import create_scheduler_service

from .models import (
    LifecycleSettingsModel,
    SchedulerSettingsModel,
    SchedulerSettingsUpdate,
    SchedulerStatusResponse,
    to_model,
)

router = APIRouter()


# =============================================================================
# LIFECYCLE SETTINGS
# =============================================================================


@router.get("/settings/lifecycle", response_model=LifecycleSettingsModel)
def get_lifecycle_settings():
    """Get channel lifecycle settings."""
    from teamarr.database.settings import get_lifecycle_settings

    with get_db() as conn:
        settings = get_lifecycle_settings(conn)

    return to_model(LifecycleSettingsModel, settings)


@router.put("/settings/lifecycle", response_model=LifecycleSettingsModel)
def update_lifecycle_settings(update: LifecycleSettingsModel):
    """Update channel lifecycle settings."""
    from teamarr.database.settings import (
        get_lifecycle_settings,
        update_lifecycle_settings,
    )

    # Validate timing values
    valid_create = {"same_day", "before_event"}
    valid_delete = {"same_day", "after_event"}

    if update.channel_create_timing not in valid_create:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid channel_create_timing. Valid: {sorted(valid_create)}",
        )
    if update.channel_delete_timing not in valid_delete:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid channel_delete_timing. Valid: {sorted(valid_delete)}",
        )

    # Validate buffer ranges (0 to 20160 minutes = 2 weeks)
    if not (0 <= update.channel_pre_buffer_minutes <= 20160):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="channel_pre_buffer_minutes must be between 0 and 20160",
        )
    if not (0 <= update.channel_post_buffer_minutes <= 20160):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="channel_post_buffer_minutes must be between 0 and 20160",
        )

    with get_db() as conn:
        update_lifecycle_settings(
            conn,
            channel_create_timing=update.channel_create_timing,
            channel_delete_timing=update.channel_delete_timing,
            channel_pre_buffer_minutes=update.channel_pre_buffer_minutes,
            channel_post_buffer_minutes=update.channel_post_buffer_minutes,
            channel_range_start=update.channel_range_start,
            channel_range_end=update.channel_range_end,
        )

    with get_db() as conn:
        settings = get_lifecycle_settings(conn)

    return to_model(LifecycleSettingsModel, settings)


# =============================================================================
# SCHEDULER SETTINGS & CONTROL
# =============================================================================


@router.get("/settings/scheduler", response_model=SchedulerSettingsModel)
def get_scheduler_settings():
    """Get scheduler settings."""
    from teamarr.database.settings import get_scheduler_settings

    with get_db() as conn:
        settings = get_scheduler_settings(conn)

    return to_model(SchedulerSettingsModel, settings)


@router.put("/settings/scheduler", response_model=SchedulerSettingsModel)
def update_scheduler_settings(update: SchedulerSettingsUpdate):
    """Update scheduler settings."""
    from croniter import croniter

    from teamarr.database.settings import (
        get_scheduler_settings,
        update_scheduler_settings,
    )

    if update.interval_minutes is not None and update.interval_minutes < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="interval_minutes must be at least 1",
        )

    # Validate cron expression if provided
    if update.channel_reset_cron:
        try:
            croniter(update.channel_reset_cron)
        except (KeyError, ValueError) as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid cron expression: {e}",
            ) from None

    with get_db() as conn:
        update_scheduler_settings(
            conn,
            enabled=update.enabled,
            interval_minutes=update.interval_minutes,
            channel_reset_enabled=update.channel_reset_enabled,
            channel_reset_cron=update.channel_reset_cron,
        )

    # Apply scheduler state change immediately if enabled was updated
    if update.enabled is not None:
        stop_lifecycle_scheduler()
        if update.enabled:
            start_lifecycle_scheduler(get_db)

    # Restart channel reset sub-scheduler if its settings changed
    if update.channel_reset_enabled is not None or update.channel_reset_cron is not None:

        restart_scheduler_sub_task("channel_reset")

    with get_db() as conn:
        settings = get_scheduler_settings(conn)

    return to_model(SchedulerSettingsModel, settings)


@router.get("/scheduler/status", response_model=SchedulerStatusResponse)
def get_scheduler_status():
    """Get current scheduler status."""

    scheduler_service = create_scheduler_service(get_db)
    status = scheduler_service.get_status()

    return SchedulerStatusResponse(
        running=status.running,
        cron_expression=status.cron_expression,
        last_run=status.last_run.isoformat() if status.last_run else None,
        next_run=status.next_run.isoformat() if status.next_run else None,
    )


@router.post("/scheduler/run")
def trigger_scheduler_run() -> dict:
    """Manually trigger a scheduler run."""

    try:
        client = get_dispatcharr_client(get_db)
    except Exception:
        client = None

    scheduler_service = create_scheduler_service(get_db, client)
    result = scheduler_service.run_once()

    return {
        "success": True,
        "results": {
            "started_at": result.started_at.isoformat() if result.started_at else None,
            "completed_at": result.completed_at.isoformat() if result.completed_at else None,
            "epg_generation": result.epg_generation,
            "deletions": result.deletions,
            "reconciliation": result.reconciliation,
            "cleanup": result.cleanup,
        },
    }
