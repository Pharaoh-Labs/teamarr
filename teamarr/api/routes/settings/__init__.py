"""Settings management endpoints.

Provides REST API for:
- Reading and updating application settings
- Testing Dispatcharr connection
- Scheduler status and control
"""

from dataclasses import asdict

from fastapi import APIRouter

from teamarr.config import get_ui_timezone_str, is_ui_timezone_from_env
from teamarr.database import get_db
from teamarr.database.settings import get_all_settings

from .channel_numbering import router as channel_numbering_router
from .channelsdvr import router as channelsdvr_router
from .dispatcharr import router as dispatcharr_router
from .display import router as display_router
from .emby import router as emby_router
from .epg import router as epg_router
from .feed_separation import router as feed_separation_router
from .jellyfin import router as jellyfin_router
from .lifecycle import router as lifecycle_router
from .models import (
    AllSettingsModel,
    ChannelNumberingSettingsModel,
    ChannelsDVRSettingsModel,
    DispatcharrSettingsModel,
    DisplaySettingsModel,
    DurationSettingsModel,
    EmbySettingsModel,
    EPGSettingsModel,
    FeedSeparationSettingsModel,
    JellyfinSettingsModel,
    LifecycleSettingsModel,
    ReconciliationSettingsModel,
    SchedulerSettingsModel,
    StreamOrderingRuleModel,
    StreamOrderingSettingsModel,
    TeamFilterSettingsModel,
    UpdateCheckSettingsModel,
)
from .stream_ordering import router as stream_ordering_router
from .team_filter import router as team_filter_router
from .update_check import router as update_check_router

# Main router that includes all sub-routers
router = APIRouter()

# Include sub-routers
router.include_router(dispatcharr_router)
router.include_router(emby_router)
router.include_router(jellyfin_router)
router.include_router(channelsdvr_router)
router.include_router(lifecycle_router)
router.include_router(epg_router)
router.include_router(display_router)
router.include_router(team_filter_router)
router.include_router(channel_numbering_router)
router.include_router(stream_ordering_router)
router.include_router(update_check_router)
router.include_router(feed_separation_router)

# =============================================================================
# MAIN SETTINGS ENDPOINT
# =============================================================================


@router.get("/settings", response_model=AllSettingsModel)
def get_settings():
    """Get all application settings."""

    with get_db() as conn:
        settings = get_all_settings(conn)

    # Field names match the dataclasses by construction (guarded by
    # tests/test_settings_registry.py); Pydantic coerces the nested dicts
    # and drops dataclass groups the API model doesn't expose.
    data = asdict(settings)
    return AllSettingsModel(
        **{k: v for k, v in data.items() if k in AllSettingsModel.model_fields},
        ui_timezone=get_ui_timezone_str(),
        ui_timezone_source="env" if is_ui_timezone_from_env() else "epg",
    )


# Export models for external use
__all__ = [
    "router",
    "AllSettingsModel",
    "ChannelNumberingSettingsModel",
    "ChannelsDVRSettingsModel",
    "DispatcharrSettingsModel",
    "DisplaySettingsModel",
    "DurationSettingsModel",
    "EmbySettingsModel",
    "EPGSettingsModel",
    "FeedSeparationSettingsModel",
    "JellyfinSettingsModel",
    "LifecycleSettingsModel",
    "ReconciliationSettingsModel",
    "SchedulerSettingsModel",
    "StreamOrderingRuleModel",
    "StreamOrderingSettingsModel",
    "TeamFilterSettingsModel",
    "UpdateCheckSettingsModel",
]
