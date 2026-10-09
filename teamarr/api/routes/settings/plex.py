"""Plex settings, connection test, and DVR/device discovery endpoints."""

from fastapi import APIRouter

from teamarr.database import get_db
from teamarr.plex.client import PlexClient

from .models import (
    MASKED_SECRET,
    PlexConnectionTestRequest,
    PlexConnectionTestResponse,
    PlexDeviceModel,
    PlexDvrModel,
    PlexDvrsResponse,
    PlexSettingsModel,
    PlexSettingsUpdate,
    merge_masked_servers,
    to_model,
)

router = APIRouter()


@router.get("/settings/plex", response_model=PlexSettingsModel)
def get_plex_settings():
    """Get Plex integration settings."""
    from teamarr.database.settings import get_plex_settings

    with get_db() as conn:
        settings = get_plex_settings(conn)

    return to_model(PlexSettingsModel, settings)


@router.put("/settings/plex", response_model=PlexSettingsModel)
def update_plex_settings(update: PlexSettingsUpdate):
    """Update Plex integration settings."""
    from teamarr.database.settings import get_plex_settings, update_plex_settings

    servers = None
    if update.servers is not None:
        with get_db() as conn:
            stored = get_plex_settings(conn).servers
        servers = merge_masked_servers([s.model_dump() for s in update.servers], stored)

    with get_db() as conn:
        update_plex_settings(conn, enabled=update.enabled, servers=servers)

    with get_db() as conn:
        settings = get_plex_settings(conn)

    return to_model(PlexSettingsModel, settings)


def _resolve_url_token(request: PlexConnectionTestRequest | None) -> tuple[str, str]:
    """Resolve (url, token) from an optional request against saved settings.

    With no request (or no `url`), use the first saved server's url+token.
    A masked token ("********") resolves only against the saved server whose
    URL exactly matches the request — NOT against any other saved server.
    Falling back to a different server's token here would send that
    server's real credential to whatever host the caller just typed into
    the URL field (e.g. mid-edit, before saving).
    """
    from teamarr.database.settings import get_plex_settings

    with get_db() as conn:
        saved = get_plex_settings(conn)

    if not request or not request.url:
        first = saved.servers[0] if saved.servers else None
        return (first.url if first else "") or "", (first.token if first else "") or ""

    url = request.url
    match = next((s for s in saved.servers if s.url == url), None)
    token = request.token or ""
    if token == MASKED_SECRET:
        token = (match.token if match else "") or ""
    return url, token


@router.post("/plex/test", response_model=PlexConnectionTestResponse)
def test_plex_connection(request: PlexConnectionTestRequest | None = None):
    """Test connection to a Plex server.

    If no parameters provided, tests with the first saved server.
    """
    url, token = _resolve_url_token(request)
    if not url:
        return PlexConnectionTestResponse(success=False, error="No Plex URL configured")
    if not token:
        return PlexConnectionTestResponse(success=False, error="No Plex token configured")

    client = PlexClient(base_url=url, token=token)
    result = client.test_connection()

    return PlexConnectionTestResponse(
        success=result.get("success", False),
        dvr_count=result.get("dvr_count"),
        error=result.get("error"),
    )


@router.post("/plex/dvrs", response_model=PlexDvrsResponse)
def list_plex_dvrs(request: PlexConnectionTestRequest | None = None):
    """List DVRs and their HDHomeRun devices, for the device picker.

    Falls back to the saved URL/token when not provided. A masked token
    ("********") resolves against the saved server matching `url`.

    POST (not GET) so the token never travels in a URL query string —
    unlike `url`, it's a live credential that would otherwise land in
    access logs and browser history on every keystroke-triggered request.
    """
    resolved_url, resolved_token = _resolve_url_token(request)

    if not resolved_url:
        return PlexDvrsResponse(success=False, error="No Plex URL configured")
    if not resolved_token:
        return PlexDvrsResponse(success=False, error="No Plex token configured")

    client = PlexClient(base_url=resolved_url, token=resolved_token)
    result = client.list_dvrs()

    if not result.get("success"):
        return PlexDvrsResponse(success=False, error=result.get("error"))

    dvrs = [
        PlexDvrModel(
            key=dvr.key,
            lineup_title=dvr.lineup_title,
            devices=[
                PlexDeviceModel(
                    key=device.key,
                    device_id=device.device_id,
                    uri=device.uri,
                    profile_hint=device.profile_hint,
                    channel_count=len(
                        [m for m in device.channel_mapping if m.enabled]
                    ),
                )
                for device in dvr.devices
            ],
        )
        for dvr in result["dvrs"]
    ]
    return PlexDvrsResponse(success=True, dvrs=dvrs)
