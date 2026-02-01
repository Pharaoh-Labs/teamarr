"""Stream filter settings endpoints.

Provides REST API for managing the global stream filtering defaults
that apply to event groups unless they override settings.
"""

from fastapi import APIRouter

from teamarr.database import get_db
from teamarr.database.settings import get_stream_filter_settings, update_stream_filter_settings

from .models import StreamFilterSettingsModel, StreamFilterSettingsUpdate

router = APIRouter()


@router.get("/settings/stream-filter", response_model=StreamFilterSettingsModel)
def get_stream_filter():
    """Get global stream filter settings."""
    with get_db() as conn:
        settings = get_stream_filter_settings(conn)

    return StreamFilterSettingsModel(
        require_event_pattern=settings.require_event_pattern,
        include_patterns=settings.include_patterns,
        exclude_patterns=settings.exclude_patterns,
    )


@router.put("/settings/stream-filter", response_model=StreamFilterSettingsModel)
def update_stream_filter(update: StreamFilterSettingsUpdate):
    """Update global stream filter settings."""
    with get_db() as conn:
        update_stream_filter_settings(
            conn,
            require_event_pattern=update.require_event_pattern,
            include_patterns=update.include_patterns,
            exclude_patterns=update.exclude_patterns,
        )
        settings = get_stream_filter_settings(conn)

    return StreamFilterSettingsModel(
        require_event_pattern=settings.require_event_pattern,
        include_patterns=settings.include_patterns,
        exclude_patterns=settings.exclude_patterns,
    )
