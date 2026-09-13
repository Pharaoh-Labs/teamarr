"""Managed Team EPG channel settings endpoints."""

from fastapi import APIRouter, HTTPException

from teamarr.database import get_db
from teamarr.database.settings import (
    get_managed_team_channel_settings,
    update_managed_team_channel_settings,
)

from .models import ManagedTeamChannelSettingsModel, ManagedTeamChannelSettingsUpdate, to_model

router = APIRouter()


@router.get("/settings/managed-team-channels", response_model=ManagedTeamChannelSettingsModel)
def get_settings():
    """Get persistent Team EPG channel numbering settings."""
    with get_db() as conn:
        return to_model(ManagedTeamChannelSettingsModel, get_managed_team_channel_settings(conn))


@router.put("/settings/managed-team-channels", response_model=ManagedTeamChannelSettingsModel)
def update_settings(update: ManagedTeamChannelSettingsUpdate):
    """Update the dedicated range and explicit priority order for Team EPG channels."""
    if update.range_start is not None and update.range_start < 1:
        raise HTTPException(status_code=400, detail="range_start must be at least 1")
    if update.range_end is not None and update.range_end < 1:
        raise HTTPException(status_code=400, detail="range_end must be at least 1")
    if (
        update.range_start is not None
        and update.range_end is not None
        and update.range_end < update.range_start
    ):
        raise HTTPException(
            status_code=400,
            detail="range_end must be greater than or equal to range_start",
        )
    if update.priority_ids is not None:
        if any(team_id < 1 for team_id in update.priority_ids):
            raise HTTPException(
                status_code=400, detail="priority_ids must contain positive team IDs"
            )
        if len(update.priority_ids) != len(set(update.priority_ids)):
            raise HTTPException(status_code=400, detail="priority_ids must not contain duplicates")

    with get_db() as conn:
        current = get_managed_team_channel_settings(conn)
        range_start = update.range_start if update.range_start is not None else current.range_start
        range_end = update.range_end if update.range_end is not None else current.range_end
        if range_end is not None and range_end < range_start:
            raise HTTPException(
                status_code=400,
                detail="range_end must be greater than or equal to range_start",
            )
        changes = update.model_dump(exclude_unset=True)
        update_managed_team_channel_settings(conn, **changes)
        return to_model(ManagedTeamChannelSettingsModel, get_managed_team_channel_settings(conn))
