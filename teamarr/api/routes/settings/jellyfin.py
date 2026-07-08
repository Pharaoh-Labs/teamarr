"""Jellyfin settings and connection test endpoints."""

from fastapi import APIRouter

from teamarr.database import get_db
from teamarr.jellyfin.client import JellyfinClient

from .models import (
    JellyfinConnectionTestRequest,
    JellyfinConnectionTestResponse,
    JellyfinSettingsModel,
    JellyfinSettingsUpdate,
    to_model,
    unmask_or_skip,
)

router = APIRouter()


@router.get("/settings/jellyfin", response_model=JellyfinSettingsModel)
def get_jellyfin_settings():
    """Get Jellyfin integration settings."""
    from teamarr.database.settings import get_jellyfin_settings

    with get_db() as conn:
        settings = get_jellyfin_settings(conn)

    return to_model(JellyfinSettingsModel, settings)


@router.put("/settings/jellyfin", response_model=JellyfinSettingsModel)
def update_jellyfin_settings(update: JellyfinSettingsUpdate):
    """Update Jellyfin integration settings."""
    from teamarr.database.settings import (
        get_jellyfin_settings,
        update_jellyfin_settings,
    )

    with get_db() as conn:
        update_jellyfin_settings(
            conn,
            enabled=update.enabled,
            url=update.url,
            username=update.username,
            password=unmask_or_skip(update.password),
            api_key=unmask_or_skip(update.api_key),
        )

    with get_db() as conn:
        settings = get_jellyfin_settings(conn)

    return to_model(JellyfinSettingsModel, settings)


@router.post("/jellyfin/test", response_model=JellyfinConnectionTestResponse)
def test_jellyfin_connection(
    request: JellyfinConnectionTestRequest | None = None,
):
    """Test connection to Jellyfin server.

    If no parameters provided, tests with saved settings.
    Accepts optional url/username/password overrides.
    """
    from teamarr.database.settings import get_jellyfin_settings

    with get_db() as conn:
        saved = get_jellyfin_settings(conn)

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
        return JellyfinConnectionTestResponse(
            success=False,
            error="No Jellyfin URL configured",
        )

    client = JellyfinClient(
        base_url=url,
        username=username,
        password=password,
        api_key=api_key,
    )
    result = client.test_connection()

    return JellyfinConnectionTestResponse(
        success=result.get("success", False),
        server_name=result.get("server_name"),
        server_version=result.get("server_version"),
        error=result.get("error"),
    )
