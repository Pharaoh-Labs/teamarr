"""Headendarr settings and connection endpoints."""

from fastapi import APIRouter

from teamarr.database import get_db

from .models import (
    ConnectionTestRequest,
    HeadendarrConnectionTestResponse,
    HeadendarrSettingsModel,
    HeadendarrSettingsUpdate,
    unmask_or_skip,
)

router = APIRouter()
HEADENDARR_TEAMARR_EPG_NAME = "Teamarr"
HEADENDARR_TEAMARR_EPG_SCHEDULE = "0 * * * *"


def _build_teamarr_xmltv_url(teamarr_host: str) -> str:
    base = teamarr_host.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = f"http://{base}"
    return f"{base}/api/v1/epg/xmltv"


@router.get("/settings/headendarr", response_model=HeadendarrSettingsModel)
def get_headendarr_settings():
    """Get Headendarr integration settings."""
    from teamarr.database.settings import get_headendarr_settings

    with get_db() as conn:
        settings = get_headendarr_settings(conn)

    return HeadendarrSettingsModel(
        enabled=settings.enabled,
        url=settings.url,
        username=settings.username,
        password=settings.password,
        teamarr_host=settings.teamarr_host,
    )


@router.put("/settings/headendarr", response_model=HeadendarrSettingsModel)
def update_headendarr_settings(update: HeadendarrSettingsUpdate):
    """Update Headendarr integration settings."""
    from teamarr.database.settings import (
        get_headendarr_settings,
        update_headendarr_settings,
    )
    from teamarr.headendarr import get_factory

    with get_db() as conn:
        update_headendarr_settings(
            conn,
            enabled=update.enabled,
            url=update.url,
            username=update.username,
            password=unmask_or_skip(update.password),
            teamarr_host=update.teamarr_host,
        )

    try:
        factory = get_factory()
        factory.reconnect()
    except Exception:
        pass

    with get_db() as conn:
        settings = get_headendarr_settings(conn)

    return HeadendarrSettingsModel(
        enabled=settings.enabled,
        url=settings.url,
        username=settings.username,
        password=settings.password,
        teamarr_host=settings.teamarr_host,
    )


@router.post("/headendarr/test", response_model=HeadendarrConnectionTestResponse)
def test_headendarr_connection(request: ConnectionTestRequest | None = None):
    """Test connection to Headendarr."""
    from teamarr.headendarr import get_factory

    try:
        factory = get_factory(get_db)
    except RuntimeError:
        from teamarr.headendarr.factory import HeadendarrFactory

        factory = HeadendarrFactory(get_db)

    if request:
        result = factory.test_connection(
            url=request.url,
            username=request.username,
            password=request.password,
        )
    else:
        result = factory.test_connection()

    return HeadendarrConnectionTestResponse(
        success=result.success,
        url=result.url,
        username=result.username,
        version=result.version,
        playlist_count=result.playlist_count,
        epg_count=result.epg_count,
        error=result.error,
    )


@router.get("/headendarr/status")
def get_headendarr_status() -> dict:
    """Get current Headendarr connection status."""
    from teamarr.headendarr import get_factory

    try:
        factory = get_factory(get_db)
        if not factory.is_configured:
            return {"configured": False, "connected": False}

        result = factory.test_connection()
        response = {"configured": True, "connected": result.success}
        if not result.success and result.error:
            response["error"] = result.error
        return response
    except RuntimeError:
        return {"configured": False, "connected": False}


@router.get("/headendarr/epg-sources")
def get_headendarr_epg_sources() -> dict:
    """Get available EPG sources from Headendarr."""
    from teamarr.headendarr import get_headendarr_connection

    try:
        conn = get_headendarr_connection(get_db)
        if not conn:
            return {
                "success": False,
                "error": "Headendarr not configured or not connected",
                "sources": [],
            }

        return {
            "success": True,
            "sources": [
                {
                    "id": source.id,
                    "name": source.name,
                    "url": source.url,
                    "enabled": source.enabled,
                    "update_schedule": source.update_schedule,
                }
                for source in conn.epg.list_sources()
            ],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "sources": []}


@router.get("/headendarr/playlists")
def get_headendarr_playlists() -> dict:
    """Get available playlists from Headendarr."""
    from teamarr.headendarr import get_headendarr_connection

    try:
        conn = get_headendarr_connection(get_db)
        if not conn:
            return {
                "success": False,
                "error": "Headendarr not configured or not connected",
                "playlists": [],
            }

        return {
            "success": True,
            "playlists": [
                {
                    "id": playlist.id,
                    "name": playlist.name,
                    "enabled": playlist.enabled,
                    "connections": playlist.connections,
                }
                for playlist in conn.playlists.list_playlists()
            ],
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "playlists": []}


@router.post("/headendarr/provision-epg")
def provision_headendarr_epg() -> dict:
    """Provision or update Teamarr's EPG source in Headendarr."""
    from teamarr.database.settings import get_headendarr_settings, update_headendarr_settings
    from teamarr.headendarr import get_headendarr_connection

    with get_db() as db_conn:
        settings = get_headendarr_settings(db_conn)

    if not settings.enabled:
        return {"success": False, "error": "Headendarr integration is disabled"}
    if not settings.teamarr_host:
        return {"success": False, "error": "Teamarr host is not configured"}

    conn = get_headendarr_connection(get_db)
    if not conn:
        return {"success": False, "error": "Headendarr not configured or not connected"}

    epg_id = conn.epg.ensure_source(
        name=HEADENDARR_TEAMARR_EPG_NAME,
        url=_build_teamarr_xmltv_url(settings.teamarr_host),
        update_schedule=HEADENDARR_TEAMARR_EPG_SCHEDULE,
    )
    if epg_id is None:
        return {"success": False, "error": "Failed to create or update Headendarr EPG source"}

    conn.epg.trigger_update(epg_id)
    return {"success": True, "epg_id": epg_id}
