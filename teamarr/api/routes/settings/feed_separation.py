"""Feed separation settings endpoints."""

from fastapi import APIRouter

from teamarr.database import get_db
from teamarr.database.settings import update_feed_separation_settings as db_update

from .models import (
    FeedSeparationSettingsModel,
    FeedSeparationSettingsUpdate,
    to_model,
)

router = APIRouter()


@router.get("/settings/feed-separation", response_model=FeedSeparationSettingsModel)
def get_feed_separation_settings():
    """Get feed separation settings."""
    from teamarr.database.settings import get_feed_separation_settings

    with get_db() as conn:
        settings = get_feed_separation_settings(conn)

    return to_model(FeedSeparationSettingsModel, settings)


@router.put("/settings/feed-separation", response_model=FeedSeparationSettingsModel)
def update_feed_separation_settings(update: FeedSeparationSettingsUpdate):
    """Update feed separation settings."""
    from teamarr.database.settings import (
        get_feed_separation_settings,
    )

    with get_db() as conn:
        db_update(conn, **update.model_dump())

    with get_db() as conn:
        settings = get_feed_separation_settings(conn)

    return to_model(FeedSeparationSettingsModel, settings)
