"""Channel numbering settings endpoints."""

from fastapi import APIRouter, HTTPException, status

from teamarr.database import get_db
from teamarr.database.channel_numbers import arm_channel_relayout, get_global_channel_mode

from .models import (
    ChannelNumberingSettingsModel,
    ChannelNumberingSettingsUpdate,
    to_model,
)

router = APIRouter()

VALID_CHANNEL_MODES = {"auto", "manual"}
VALID_CONSOLIDATION_MODES = {"consolidate", "separate"}
VALID_STABILITY_MODES = {"compact", "gap", "strict"}


@router.get("/settings/channel-numbering", response_model=ChannelNumberingSettingsModel)
def get_channel_numbering_settings():
    """Get channel numbering and consolidation settings."""
    from teamarr.database.settings import get_channel_numbering_settings

    with get_db() as conn:
        settings = get_channel_numbering_settings(conn)

    return to_model(ChannelNumberingSettingsModel, settings)


@router.put("/settings/channel-numbering", response_model=ChannelNumberingSettingsModel)
def update_channel_numbering_settings(update: ChannelNumberingSettingsUpdate):
    """Update channel numbering and consolidation settings."""
    from teamarr.database.settings import (
        get_channel_numbering_settings,
        update_channel_numbering_settings,
    )

    if update.global_channel_mode is not None:
        if update.global_channel_mode not in VALID_CHANNEL_MODES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid global_channel_mode. Valid: {VALID_CHANNEL_MODES}",
            )

    if update.global_consolidation_mode is not None:
        if update.global_consolidation_mode not in VALID_CONSOLIDATION_MODES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid global_consolidation_mode. Valid: {VALID_CONSOLIDATION_MODES}",
            )

    if update.channel_stability_mode is not None:
        if update.channel_stability_mode not in VALID_STABILITY_MODES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid channel_stability_mode. Valid: {VALID_STABILITY_MODES}",
            )

    if update.channel_gap_size is not None and update.channel_gap_size < 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="channel_gap_size must be >= 1",
        )

    if update.channel_daily_reset_time is not None:
        if not _valid_hhmm(update.channel_daily_reset_time):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="channel_daily_reset_time must be in HH:MM (24h) format",
            )

    with get_db() as conn:
        update_channel_numbering_settings(
            conn,
            global_channel_mode=update.global_channel_mode,
            league_channel_starts=update.league_channel_starts,
            global_consolidation_mode=update.global_consolidation_mode,
            channel_stability_mode=update.channel_stability_mode,
            channel_gap_size=update.channel_gap_size,
            channel_daily_reset_enabled=update.channel_daily_reset_enabled,
            channel_daily_reset_time=update.channel_daily_reset_time,
        )

    with get_db() as conn:
        settings = get_channel_numbering_settings(conn)

    return to_model(ChannelNumberingSettingsModel, settings)


@router.post(
    "/settings/channel-numbering/relayout",
    response_model=ChannelNumberingSettingsModel,
)
def request_channel_relayout():
    """Arm a one-shot full channel re-grid for the next generation run.

    Renumbers every channel back into priority order (re-applying gap spacing and
    reclaiming gaps) on the next run, bypassing the daily reset window. Only
    meaningful in gap/strict stability modes; harmless otherwise.
    """
    from teamarr.database.settings import get_channel_numbering_settings

    with get_db() as conn:
        if get_global_channel_mode(conn) == "manual":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Re-grid applies to Auto numbering mode only.",
            )
        settings = get_channel_numbering_settings(conn)
        if settings.channel_stability_mode == "compact":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Re-grid applies to Gapped/Strict stability modes only.",
            )
        arm_channel_relayout(conn)

    with get_db() as conn:
        settings = get_channel_numbering_settings(conn)

    return to_model(ChannelNumberingSettingsModel, settings)


def _valid_hhmm(value: str) -> bool:
    """Validate an HH:MM (24h) time string."""
    try:
        hh, mm = str(value).split(":")
        return 0 <= int(hh) <= 23 and 0 <= int(mm) <= 59
    except (ValueError, AttributeError):
        return False
