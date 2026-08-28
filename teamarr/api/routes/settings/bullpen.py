"""Bullpen proxy settings endpoints.

Bullpen (https://bullpen.direct) is an optional caching proxy that fronts
several provider upstreams behind a single API key. This is a plain
settings CRUD group (get/put) with no connection-test endpoint.
"""

from fastapi import APIRouter

from teamarr.database import get_db
from teamarr.providers.registry import ProviderRegistry

from .models import MASKED_SECRET, BullpenSettingsModel, BullpenSettingsUpdate, to_model

router = APIRouter()


@router.get("/settings/bullpen", response_model=BullpenSettingsModel)
def get_bullpen_settings():
    """Get bullpen proxy settings."""
    from teamarr.database.settings import get_bullpen_settings

    with get_db() as conn:
        settings = get_bullpen_settings(conn)

    return to_model(BullpenSettingsModel, settings)


@router.put("/settings/bullpen", response_model=BullpenSettingsModel)
def update_bullpen_settings(update: BullpenSettingsUpdate):
    """Update bullpen proxy settings."""
    from teamarr.database.settings import get_bullpen_settings, update_bullpen_settings

    payload = update.model_dump(exclude_unset=True)
    if payload.get("api_key") == MASKED_SECRET:
        payload.pop("api_key")
    if payload.get("enabled"):
        payload.update(disabled_reason=None, disabled_at=None)

    with get_db() as conn:
        update_bullpen_settings(conn, **payload)

    for provider in (
        "espn",
        "bellmedia",
        "squiggle",
        "nascar",
        "mlbstats",
        "hockeytech",
        "tsdb",
    ):
        ProviderRegistry.reinitialize_provider(provider)

    with get_db() as conn:
        settings = get_bullpen_settings(conn)

    return to_model(BullpenSettingsModel, settings)
