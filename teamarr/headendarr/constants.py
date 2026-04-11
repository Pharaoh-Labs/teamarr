"""Shared constants for Headendarr integration."""

HEADENDARR_TEAMARR_EPG_NAME = "Teamarr"
HEADENDARR_TEAMARR_EPG_SCHEDULE = "0 * * * *"


def build_teamarr_xmltv_url(teamarr_host: str) -> str:
    base = teamarr_host.strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = f"http://{base}"
    return f"{base}/api/v1/epg/xmltv"
