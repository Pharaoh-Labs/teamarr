"""Bullpen proxy settings endpoints.

Bullpen (https://bullpen.direct) is an optional caching proxy that fronts
several provider upstreams behind a single API key. This is a plain
settings CRUD group (get/put) with no connection-test endpoint.
"""

from fastapi import APIRouter

from teamarr.database import get_db

from .models import BullpenSettingsModel, BullpenSettingsUpdate, to_model, unmask_or_skip

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

    payload = update.model_dump()
    payload["api_key"] = unmask_or_skip(update.api_key)

    with get_db() as conn:
        update_bullpen_settings(conn, **payload)

    with get_db() as conn:
        settings = get_bullpen_settings(conn)

    return to_model(BullpenSettingsModel, settings)
