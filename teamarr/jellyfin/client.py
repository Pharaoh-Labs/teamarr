"""Jellyfin server client for Live TV guide refresh.

Jellyfin forked from Emby in 2018 and inherited a near-identical API
surface. The only structural difference Teamarr cares about is the URL
prefix: Emby mounts under ``/emby/...`` while Jellyfin serves the same
endpoints at the server root. ``X-Emby-Token`` (the API-key header)
still works on Jellyfin for back-compat.

This client therefore subclasses EmbyClient and only swaps the prefix.
"""

from teamarr.emby.client import EmbyClient


class JellyfinClient(EmbyClient):
    """Client for Jellyfin server API interactions."""

    PATH_PREFIX = ""
    SERVER_LABEL = "JELLYFIN"
