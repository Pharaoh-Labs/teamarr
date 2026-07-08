"""Emby settings and connection test endpoints."""

from fastapi import APIRouter

from teamarr.database import get_db
from teamarr.emby.client import EmbyClient

from .models import (
    EmbyConnectionTestRequest,
    EmbyConnectionTestResponse,
    EmbySettingsModel,
    EmbySettingsUpdate,
    to_model,
    unmask_or_skip,
)

router = APIRouter()


@router.get("/settings/emby", response_model=EmbySettingsModel)
def get_emby_settings():
    """Get Emby integration settings."""
    from teamarr.database.settings import get_emby_settings

    with get_db() as conn:
        settings = get_emby_settings(conn)

    return to_model(EmbySettingsModel, settings)


@router.put("/settings/emby", response_model=EmbySettingsModel)
def update_emby_settings(update: EmbySettingsUpdate):
    """Update Emby integration settings."""
    from teamarr.database.settings import (
        get_emby_settings,
        update_emby_settings,
    )

    with get_db() as conn:
        update_emby_settings(
            conn,
            enabled=update.enabled,
            url=update.url,
            username=update.username,
            password=unmask_or_skip(update.password),
            api_key=unmask_or_skip(update.api_key),
        )

    with get_db() as conn:
        settings = get_emby_settings(conn)

    return to_model(EmbySettingsModel, settings)


@router.post("/emby/test", response_model=EmbyConnectionTestResponse)
def test_emby_connection(
    request: EmbyConnectionTestRequest | None = None,
):
    """Test connection to Emby server.

    If no parameters provided, tests with saved settings.
    Accepts optional url/username/password overrides.
    """
    from teamarr.database.settings import get_emby_settings

    with get_db() as conn:
        saved = get_emby_settings(conn)

    url = (request.url if request and request.url else saved.url) or ""
    username = (
        request.username if request and request.username else saved.username
    ) or ""
    password = (
        request.password if request and request.password else saved.password
    ) or ""
    api_key = (
        request.api_key if request and request.api_key else saved.api_key
    )

    if not url:
        return EmbyConnectionTestResponse(
            success=False,
            error="No Emby URL configured",
        )

    client = EmbyClient(
        base_url=url,
        username=username,
        password=password,
        api_key=api_key,
    )
    result = client.test_connection()

    return EmbyConnectionTestResponse(
        success=result.get("success", False),
        server_name=result.get("server_name"),
        server_version=result.get("server_version"),
        error=result.get("error"),
    )
