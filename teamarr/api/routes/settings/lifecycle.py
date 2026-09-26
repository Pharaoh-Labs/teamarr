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
    SportLeadTimeOverride,
    SportLeadTimeUpdate,
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
        mode=status.mode,
        cron_expression=status.cron_expression,
        pre_match_lead_minutes=status.pre_match_lead_minutes,
        discovery_interval_hours=status.discovery_interval_hours,
        last_run=status.last_run.isoformat() if status.last_run else None,
        next_run=status.next_run.isoformat() if status.next_run else None,
        next_run_reason=status.next_run_reason,
        next_match_start=status.next_match_start.isoformat() if status.next_match_start else None,
        next_match_sport=status.next_match_sport,
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


# =============================================================================
# PER-SPORT PRE-MATCH LEAD TIME OVERRIDES
#
# A sport with no override here uses epg_settings.pre_match_lead_minutes (the
# global default). The scheduler reads these fresh on every computation, so
# changes here take effect on the next run — no restart needed.
# =============================================================================


@router.get("/settings/scheduler/sport-lead-times", response_model=list[SportLeadTimeOverride])
def get_sport_lead_times():
    """Get all per-sport pre-match lead time overrides."""
    from teamarr.database.sport_schedule import get_sport_lead_overrides_with_display

    with get_db() as conn:
        overrides = get_sport_lead_overrides_with_display(conn)

    return [
        SportLeadTimeOverride(
            sport=o.sport,
            pre_match_lead_minutes=o.pre_match_lead_minutes,
            display_name=o.display_name,
        )
        for o in overrides
    ]


@router.put(
    "/settings/scheduler/sport-lead-times/{sport}", response_model=list[SportLeadTimeOverride]
)
def set_sport_lead_time(sport: str, update: SportLeadTimeUpdate):
    """Set (or update) a sport's pre-match lead time override."""
    from teamarr.database.sport_schedule import (
        get_sport_lead_overrides_with_display,
        upsert_sport_lead_override,
    )

    if update.pre_match_lead_minutes < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="pre_match_lead_minutes must be 0 or greater",
        )

    with get_db() as conn:
        if not upsert_sport_lead_override(conn, sport, update.pre_match_lead_minutes):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to save sport lead time override",
            )
        overrides = get_sport_lead_overrides_with_display(conn)

    return [
        SportLeadTimeOverride(
            sport=o.sport,
            pre_match_lead_minutes=o.pre_match_lead_minutes,
            display_name=o.display_name,
        )
        for o in overrides
    ]


@router.delete(
    "/settings/scheduler/sport-lead-times/{sport}", response_model=list[SportLeadTimeOverride]
)
def delete_sport_lead_time(sport: str):
    """Remove a sport's override, reverting it to the global default."""
    from teamarr.database.sport_schedule import (
        delete_sport_lead_override,
        get_sport_lead_overrides_with_display,
    )

    with get_db() as conn:
        if not delete_sport_lead_override(conn, sport):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to remove sport lead time override",
            )
        overrides = get_sport_lead_overrides_with_display(conn)

    return [
        SportLeadTimeOverride(
            sport=o.sport,
            pre_match_lead_minutes=o.pre_match_lead_minutes,
            display_name=o.display_name,
        )
        for o in overrides
    ]
