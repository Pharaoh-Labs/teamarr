

"""NFHS provider settings routes."""

from fastapi import APIRouter, Depends
from sqlite3 import Connection

from teamarr.database.connection import get_connection
from teamarr.database.settings.read import get_nfhs_settings
from teamarr.database.settings.update import update_nfhs_settings

from .models import NFHSSettingsModel, NFHSSettingsUpdate

router = APIRouter(prefix="/settings/nfhs", tags=["settings"])


@router.get("", response_model=NFHSSettingsModel)
def get_settings(conn: Connection = Depends(get_connection)) -> NFHSSettingsModel:
    """Get NFHS high school sports provider settings."""

    settings = get_nfhs_settings(conn)

    return NFHSSettingsModel(
        enabled=settings.enabled,
        state_codes=settings.state_codes,
    )


@router.put("", response_model=NFHSSettingsModel)
def update_settings(
    payload: NFHSSettingsUpdate,
    conn: Connection = Depends(get_connection),
) -> NFHSSettingsModel:
    """Update NFHS high school sports provider settings."""

    update_nfhs_settings(
        conn,
        enabled=payload.enabled,
        state_codes=payload.state_codes,
    )

    settings = get_nfhs_settings(conn)

    return NFHSSettingsModel(
        enabled=settings.enabled,
        state_codes=settings.state_codes,
    )