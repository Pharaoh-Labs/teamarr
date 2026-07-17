"""Emby settings and connection test endpoints."""

from fastapi import APIRouter

from teamarr.database import get_db
from teamarr.emby.client import EmbyClient

from .models import (
    MASKED_SECRET,
    EmbyConnectionTestRequest,
    EmbyConnectionTestResponse,
    EmbySettingsModel,
    EmbySettingsUpdate,
    merge_masked_servers,
    to_model,
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

    servers = None
    if update.servers is not None:
        with get_db() as conn:
            stored = get_emby_settings(conn).servers
        servers = merge_masked_servers(
            [s.model_dump() for s in update.servers], stored
        )

    with get_db() as conn:
        update_emby_settings(conn, enabled=update.enabled, servers=servers)

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

    # Multi-server (#471): the UI passes explicit fields per server row;
    # the saved fallback uses the first configured server. A row's untouched
    # secret fields arrive as the masked sentinel — resolve them against the
    # saved server matching the request URL (fallback: first server).
    first = saved.servers[0] if saved.servers else None
    if request:
        match = next(
            (s for s in saved.servers if s.url and s.url == request.url), first
        )
        if request.password == MASKED_SECRET:
            request.password = match.password if match else None
        if request.api_key == MASKED_SECRET:
            request.api_key = match.api_key if match else None
    url = (request.url if request and request.url else (first.url if first else None)) or ""
    username = (
        request.username
        if request and request.username
        else (first.username if first else None)
    ) or ""
    password = (
        request.password
        if request and request.password
        else (first.password if first else None)
    ) or ""
    api_key = (
        request.api_key if request and request.api_key else (first.api_key if first else None)
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
