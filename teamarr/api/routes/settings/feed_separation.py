"""Feed separation settings endpoints."""

from fastapi import APIRouter

from teamarr.database import get_db
from teamarr.database.settings import update_feed_separation_settings as db_update

from .models import (
    FeedSeparationSettingsModel,
    FeedSeparationSettingsUpdate,
)

router = APIRouter()


@router.get("/settings/feed-separation", response_model=FeedSeparationSettingsModel)
def get_feed_separation_settings():
    """Get feed separation settings."""
    from teamarr.database.settings import get_feed_separation_settings

    with get_db() as conn:
        settings = get_feed_separation_settings(conn)

    return FeedSeparationSettingsModel(
        enabled=settings.enabled,
        home_terms=settings.home_terms,
        away_terms=settings.away_terms,
        detect_team_names=settings.detect_team_names,
        label_style=settings.label_style,
    )


@router.put("/settings/feed-separation", response_model=FeedSeparationSettingsModel)
def update_feed_separation_settings(update: FeedSeparationSettingsUpdate):
    """Update feed separation settings."""
    from teamarr.database.settings import (
        get_feed_separation_settings,
    )

    with get_db() as conn:
        db_update(
            conn,
            enabled=update.enabled,
            home_terms=update.home_terms,
            away_terms=update.away_terms,
            detect_team_names=update.detect_team_names,
            label_style=update.label_style,
        )

    with get_db() as conn:
        settings = get_feed_separation_settings(conn)

    return FeedSeparationSettingsModel(
        enabled=settings.enabled,
        home_terms=settings.home_terms,
        away_terms=settings.away_terms,
        detect_team_names=settings.detect_team_names,
        label_style=settings.label_style,
    )
