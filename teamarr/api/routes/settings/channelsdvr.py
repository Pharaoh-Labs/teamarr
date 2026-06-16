"""Channels DVR settings and connection test endpoints."""

from fastapi import APIRouter

from teamarr.database import get_db

from .models import (
    ChannelsDVRConnectionTestRequest,
    ChannelsDVRConnectionTestResponse,
    ChannelsDVRLineup,
    ChannelsDVRLineupsResponse,
    ChannelsDVRSettingsModel,
    ChannelsDVRSettingsUpdate,
    ChannelsDVRSourcesResponse,
)

router = APIRouter()


@router.get("/settings/channelsdvr", response_model=ChannelsDVRSettingsModel)
def get_channelsdvr_settings():
    """Get Channels DVR integration settings."""
    from teamarr.database.settings import get_channelsdvr_settings

    with get_db() as conn:
        settings = get_channelsdvr_settings(conn)

    return ChannelsDVRSettingsModel(
        enabled=settings.enabled,
        url=settings.url,
        source_name=settings.source_name,
        lineup_id=settings.lineup_id,
    )


@router.put("/settings/channelsdvr", response_model=ChannelsDVRSettingsModel)
def update_channelsdvr_settings(update: ChannelsDVRSettingsUpdate):
    """Update Channels DVR integration settings."""
    from teamarr.database.settings import (
        get_channelsdvr_settings,
        update_channelsdvr_settings,
    )

    with get_db() as conn:
        update_channelsdvr_settings(
            conn,
            enabled=update.enabled,
            url=update.url,
            source_name=update.source_name,
            lineup_id=update.lineup_id,
        )

    with get_db() as conn:
        settings = get_channelsdvr_settings(conn)

    return ChannelsDVRSettingsModel(
        enabled=settings.enabled,
        url=settings.url,
        source_name=settings.source_name,
        lineup_id=settings.lineup_id,
    )


@router.post("/channelsdvr/test", response_model=ChannelsDVRConnectionTestResponse)
def test_channelsdvr_connection(
    request: ChannelsDVRConnectionTestRequest | None = None,
):
    """Test connection to Channels DVR server.

    If no parameters provided, tests with saved settings.
    Accepts optional url/source_name overrides.
    """
    from teamarr.channelsdvr.client import ChannelsDVRClient
    from teamarr.database.settings import get_channelsdvr_settings

    with get_db() as conn:
        saved = get_channelsdvr_settings(conn)

    url = (request.url if request and request.url else saved.url) or ""
    source_name = (
        request.source_name if request and request.source_name else saved.source_name
    ) or ""

    if not url:
        return ChannelsDVRConnectionTestResponse(
            success=False,
            error="No Channels DVR URL configured",
        )

    client = ChannelsDVRClient(base_url=url, source_name=source_name)
    result = client.test_connection()

    return ChannelsDVRConnectionTestResponse(
        success=result.get("success", False),
        server_version=result.get("server_version"),
        source_name=result.get("source_name"),
        error=result.get("error"),
    )


@router.get("/channelsdvr/sources", response_model=ChannelsDVRSourcesResponse)
def list_channelsdvr_sources(url: str | None = None):
    """List M3U sources configured on the Channels DVR server.

    Used by the settings UI to populate the source-name dropdown.
    Falls back to the saved URL when none is provided.
    """
    from teamarr.channelsdvr.client import ChannelsDVRClient
    from teamarr.database.settings import get_channelsdvr_settings

    if not url:
        with get_db() as conn:
            saved = get_channelsdvr_settings(conn)
        url = saved.url or ""

    if not url:
        return ChannelsDVRSourcesResponse(
            success=False,
            error="No Channels DVR URL configured",
        )

    client = ChannelsDVRClient(base_url=url)
    result = client.list_m3u_sources()

    return ChannelsDVRSourcesResponse(
        success=result.get("success", False),
        sources=result.get("sources", []),
        error=result.get("error"),
    )


@router.get("/channelsdvr/lineups", response_model=ChannelsDVRLineupsResponse)
def list_channelsdvr_lineups(url: str | None = None):
    """List XMLTV lineups configured on the Channels DVR server.

    Used by the settings UI to populate the lineup dropdown. The
    selected lineup ID is what we PUT to ``/dvr/lineups/<id>`` to
    refresh the EPG.
    """
    from teamarr.channelsdvr.client import ChannelsDVRClient
    from teamarr.database.settings import get_channelsdvr_settings

    if not url:
        with get_db() as conn:
            saved = get_channelsdvr_settings(conn)
        url = saved.url or ""

    if not url:
        return ChannelsDVRLineupsResponse(
            success=False,
            error="No Channels DVR URL configured",
        )

    client = ChannelsDVRClient(base_url=url)
    result = client.list_lineups()

    return ChannelsDVRLineupsResponse(
        success=result.get("success", False),
        lineups=[
            ChannelsDVRLineup(id=lineup["id"], name=lineup["name"])
            for lineup in result.get("lineups", [])
        ],
        error=result.get("error"),
    )
