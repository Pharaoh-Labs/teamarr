"""Jellyfin server client for Live TV guide refresh.

Jellyfin forked from Emby in 2018 and inherited a near-identical API
surface. Two things differ for Teamarr:

* URL prefix — Emby mounts under ``/emby/...``, Jellyfin serves the same
  endpoints at the server root.
* Auth headers — Jellyfin 12 removed the legacy ``X-Emby-Authorization`` /
  ``X-Emby-Token`` headers (#749). Jellyfin's own scheme is the standard
  ``Authorization`` header with the ``MediaBrowser`` value, and the access
  token or API key rides inside it as ``Token="..."``. Older Jellyfin
  (10.x) accepts that form too, so there is no version switch. Emby keeps
  its ``X-Emby-*`` headers — they are not deprecated there.

This client therefore subclasses EmbyClient and overrides only those two.
"""

from teamarr.emby.client import MEDIABROWSER_AUTH_HEADER, EmbyClient


class JellyfinClient(EmbyClient):
    """Client for Jellyfin server API interactions."""

    PATH_PREFIX = ""
    SERVER_LABEL = "JELLYFIN"

    def _auth_headers(self) -> dict[str, str]:
        """Headers for unauthenticated requests (``AuthenticateByName``)."""
        return {
            "Authorization": MEDIABROWSER_AUTH_HEADER,
            "Content-Type": "application/json",
        }

    def _token_headers(self) -> dict[str, str]:
        """Headers for authenticated requests: API key or session token."""
        if not self._access_token:
            raise RuntimeError("Not authenticated — call authenticate() first")
        # Quotes cannot appear in a Jellyfin API key or session token; strip
        # any anyway so a pasted value can never break the header grammar.
        token = self._access_token.replace('"', "")
        return {"Authorization": f'{MEDIABROWSER_AUTH_HEADER}, Token="{token}"'}
