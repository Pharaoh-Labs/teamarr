"""Smoke tests for JellyfinClient.

JellyfinClient subclasses EmbyClient and only differs in URL prefix:
Emby uses /emby/..., Jellyfin uses the server root. These tests pin
that contract so nobody collapses the two paths by accident.
"""

from teamarr.emby.client import EmbyClient
from teamarr.jellyfin.client import JellyfinClient


class TestUrlPrefix:
    def test_emby_uses_emby_prefix(self):
        client = EmbyClient(base_url="http://emby:8096")
        assert client._url("/ScheduledTasks") == "http://emby:8096/emby/ScheduledTasks"

    def test_jellyfin_omits_emby_prefix(self):
        client = JellyfinClient(base_url="http://jellyfin:8096")
        assert client._url("/ScheduledTasks") == "http://jellyfin:8096/ScheduledTasks"

    def test_jellyfin_strips_trailing_slash(self):
        client = JellyfinClient(base_url="http://jellyfin:8096/")
        assert client._url("/System/Info/Public") == "http://jellyfin:8096/System/Info/Public"

    def test_jellyfin_inherits_emby_token_header(self):
        # Jellyfin accepts X-Emby-Token for back-compat — same auth path as Emby.
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="abc")
        assert client._token_headers() == {"X-Emby-Token": "abc"}
