"""Smoke tests for JellyfinClient.

JellyfinClient subclasses EmbyClient and differs in two ways: the URL
prefix (Emby uses /emby/..., Jellyfin the server root) and the auth
headers (Jellyfin 12 dropped the legacy X-Emby-* family, #749). These
tests pin both contracts so nobody collapses the two paths by accident.
"""

import httpx
import pytest

from teamarr.emby.client import MEDIABROWSER_AUTH_HEADER, EmbyClient
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


class TestAuthHeaders:
    """Jellyfin speaks ``Authorization: MediaBrowser …``; Emby keeps X-Emby-*."""

    def test_emby_keeps_legacy_token_header(self):
        client = EmbyClient(base_url="http://emby:8096", api_key="abc")
        assert client._token_headers() == {"X-Emby-Token": "abc"}
        assert "X-Emby-Authorization" in client._auth_headers()

    def test_jellyfin_api_key_rides_in_authorization_header(self):
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="abc")
        headers = client._token_headers()
        assert "X-Emby-Token" not in headers
        assert headers["Authorization"] == (
            'MediaBrowser Client="Teamarr", Device="Server",'
            ' DeviceId="teamarr", Version="1.0", Token="abc"'
        )

    def test_jellyfin_unauthenticated_header_has_no_token(self):
        client = JellyfinClient(base_url="http://jellyfin:8096")
        headers = client._auth_headers()
        assert "X-Emby-Authorization" not in headers
        assert headers["Authorization"] == MEDIABROWSER_AUTH_HEADER
        assert "Token=" not in headers["Authorization"]

    def test_jellyfin_token_headers_require_auth(self):
        client = JellyfinClient(base_url="http://jellyfin:8096")
        with pytest.raises(RuntimeError):
            client._token_headers()

    def test_jellyfin_strips_quotes_from_token(self):
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key='a"b')
        assert client._token_headers()["Authorization"].endswith('Token="ab"')


class TestAuthenticateWireFormat:
    """The header actually leaves the process on every authenticated call."""

    def test_api_key_validation_sends_mediabrowser_header(self, monkeypatch):
        seen: dict = {}

        def fake_get(url, headers=None, timeout=None, **_):
            seen["url"] = url
            seen["headers"] = headers
            return httpx.Response(200, json=[], request=httpx.Request("GET", url))

        monkeypatch.setattr(httpx, "get", fake_get)
        client = JellyfinClient(base_url="http://jellyfin:8096", api_key="k3y")
        assert client.authenticate() is True
        assert seen["url"] == "http://jellyfin:8096/ScheduledTasks"
        assert seen["headers"]["Authorization"].endswith('Token="k3y"')
        assert "X-Emby-Token" not in seen["headers"]

    def test_password_login_uses_authorization_then_session_token(self, monkeypatch):
        posted: dict = {}

        def fake_post(url, json=None, headers=None, timeout=None, **_):
            posted["headers"] = headers
            return httpx.Response(
                200,
                json={"AccessToken": "sess", "User": {"Id": "u1"}},
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx, "post", fake_post)
        client = JellyfinClient(base_url="http://jellyfin:8096", username="u", password="p")
        assert client.authenticate() is True
        assert posted["headers"]["Authorization"] == MEDIABROWSER_AUTH_HEADER
        assert client._token_headers()["Authorization"].endswith('Token="sess"')
