"""Provider SOCKS5 proxy settings endpoints."""

from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException

from teamarr.database import get_db
from teamarr.providers import ProviderRegistry, reload_provider_request_policy

from .models import MASKED_SECRET, ProxySettingsModel, ProxySettingsUpdate, to_model

router = APIRouter()


def _validate_proxy_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "socks5" or not parsed.hostname:
        raise HTTPException(
            status_code=422,
            detail="Proxy URL must use socks5:// and include a host",
        )


@router.get("/settings/proxy", response_model=ProxySettingsModel)
def get_proxy_settings():
    """Get provider SOCKS5 proxy settings."""
    from teamarr.database.settings import get_proxy_settings

    with get_db() as conn:
        settings = get_proxy_settings(conn)
    return to_model(ProxySettingsModel, settings)


@router.get("/settings/proxy/providers", response_model=list[str])
def get_proxy_providers():
    """List registered providers eligible for the shared request policy."""
    return sorted(ProviderRegistry.enabled_provider_names())


@router.put("/settings/proxy", response_model=ProxySettingsModel)
def update_proxy_settings(update: ProxySettingsUpdate):
    """Update provider SOCKS5 settings and refresh all provider clients."""
    from teamarr.database.settings import get_proxy_settings, update_proxy_settings

    payload = update.model_dump(exclude_unset=True)
    if payload.get("url") == MASKED_SECRET:
        payload.pop("url")
    if (url := payload.get("url")) is not None:
        _validate_proxy_url(url)
    if "excluded_providers" in payload and payload["excluded_providers"] is not None:
        payload["excluded_providers"] = sorted(set(payload["excluded_providers"]))

    with get_db() as conn:
        update_proxy_settings(conn, **payload)

    reload_provider_request_policy()
    for provider in ProviderRegistry.provider_names():
        ProviderRegistry.reinitialize_provider(provider)

    with get_db() as conn:
        settings = get_proxy_settings(conn)
    return to_model(ProxySettingsModel, settings)
