"""Smoke tests for ChannelsDVRClient.

The Channels DVR REST API is unauthenticated by design on the local
network — no auth handling lives here. These tests pin URL building,
source-name encoding, and HTTP error mapping so a refactor can't
silently break the refresh hook.
"""

import time

import httpx
import pytest

from teamarr.channelsdvr.client import ChannelsDVRClient


class TestUrlBuilding:
    def test_strips_trailing_slash(self):
        client = ChannelsDVRClient(base_url="http://channels:8089/")
        assert client.base_url == "http://channels:8089"

    def test_source_path_uses_source_name(self):
        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="MyM3U")
        assert client._source_path() == "/providers/m3u/sources/MyM3U"

    def test_source_path_url_encodes_special_chars(self):
        # Spaces and slashes in source names must be percent-encoded.
        client = ChannelsDVRClient(
            base_url="http://channels:8089", source_name="My Source/With Slash"
        )
        assert client._source_path() == "/providers/m3u/sources/My%20Source%2FWith%20Slash"


class TestLineupDerivation:
    """lineup_id auto-derives from source_name (CDVR convention XMLTV-<name>)."""

    def test_explicit_lineup_is_kept(self):
        client = ChannelsDVRClient(
            base_url="http://channels:8089", source_name="MyM3U", lineup_id="XMLTV-Custom"
        )
        assert client.lineup_id == "XMLTV-Custom"
        assert client.lineup_derived is False

    def test_lineup_derived_from_source_when_absent(self):
        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="dispatcharr")
        assert client.lineup_id == "XMLTV-dispatcharr"
        assert client.lineup_derived is True

    def test_no_source_no_lineup_stays_empty(self):
        client = ChannelsDVRClient(base_url="http://channels:8089")
        assert client.lineup_id == ""
        assert client.lineup_derived is False

    def test_derived_lineup_drives_epg_refresh(self, monkeypatch):
        captured: dict = {}

        def fake_put(url, **kwargs):
            captured["url"] = url
            req = httpx.Request("PUT", url)
            return httpx.Response(200, request=req)

        monkeypatch.setattr(httpx, "put", fake_put)

        # Source only, no explicit lineup — EPG refresh should still fire.
        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="dispatcharr")
        result = client.trigger_epg_refresh()

        assert result["success"] is True
        assert captured["url"] == "http://channels:8089/dvr/lineups/XMLTV-dispatcharr"


class TestTriggerRefreshGuards:
    def test_no_source_name_returns_failure(self):
        client = ChannelsDVRClient(base_url="http://channels:8089")
        result = client.trigger_m3u_refresh()
        assert result["success"] is False
        assert "source name" in result["message"].lower()


class TestTriggerRefreshHTTP:
    def test_successful_refresh_returns_success(self, monkeypatch):
        # Real Channels DVR returns 200 with body "true"; we only need the
        # status code, but pin the method (POST) and URL so the integration
        # can't silently regress to a 404-returning verb.
        captured: dict = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            req = httpx.Request("POST", url)
            return httpx.Response(200, json=True, request=req)

        monkeypatch.setattr(httpx, "post", fake_post)

        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="MyM3U")
        result = client.trigger_m3u_refresh()

        assert result["success"] is True
        assert captured["url"] == "http://channels:8089/providers/m3u/sources/MyM3U/refresh"

    def test_404_returns_source_not_found(self, monkeypatch):
        def fake_post(url, **kwargs):
            req = httpx.Request("POST", url)
            return httpx.Response(404, request=req)

        monkeypatch.setattr(httpx, "post", fake_post)

        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="MyM3U")
        result = client.trigger_m3u_refresh()

        assert result["success"] is False
        assert "not found" in result["message"].lower()


class TestTestConnection:
    def test_status_unreachable_returns_error(self, monkeypatch):
        def fake_get(url, **kwargs):
            raise httpx.ConnectError("conn refused")

        monkeypatch.setattr(httpx, "get", fake_get)

        client = ChannelsDVRClient(base_url="http://channels:8089")
        result = client.test_connection()
        assert result["success"] is False
        assert "cannot connect" in result["error"].lower()

    def test_status_ok_no_source_returns_success(self, monkeypatch):
        def fake_get(url, **kwargs):
            req = httpx.Request("GET", url)
            return httpx.Response(200, json={"version": "2026.04.01"}, request=req)

        monkeypatch.setattr(httpx, "get", fake_get)

        client = ChannelsDVRClient(base_url="http://channels:8089")
        result = client.test_connection()
        assert result["success"] is True
        assert result["server_version"] == "2026.04.01"

    def test_source_404_returns_failure(self, monkeypatch):
        calls: list[str] = []

        def fake_get(url, **kwargs):
            calls.append(url)
            req = httpx.Request("GET", url)
            if url.endswith("/status"):
                return httpx.Response(200, json={"version": "2026.04.01"}, request=req)
            return httpx.Response(404, request=req)

        monkeypatch.setattr(httpx, "get", fake_get)

        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="missing")
        result = client.test_connection()
        assert result["success"] is False
        assert "not found" in result["error"].lower()
        assert any("/providers/m3u/sources/missing" in c for c in calls)


class TestListSources:
    def test_filters_devices_to_m3u_and_returns_friendly_names(self, monkeypatch):
        # /devices returns every tuner/provider; only Provider == "m3u" entries
        # are M3U sources, and FriendlyName is the source name we want.
        captured: dict = {}

        def fake_get(url, **kwargs):
            captured["url"] = url
            req = httpx.Request("GET", url)
            payload = [
                {
                    "Provider": "m3u",
                    "DeviceID": "M3U-dispatcharr",
                    "FriendlyName": "dispatcharr",
                },
                {
                    "Provider": "hdhr",
                    "DeviceID": "HDHR-12345",
                    "FriendlyName": "Tuner",
                },
                {
                    "Provider": "m3u",
                    "DeviceID": "M3U-other",
                    "FriendlyName": "other",
                },
            ]
            return httpx.Response(200, json=payload, request=req)

        monkeypatch.setattr(httpx, "get", fake_get)

        client = ChannelsDVRClient(base_url="http://channels:8089")
        result = client.list_m3u_sources()

        assert result["success"] is True
        assert result["sources"] == ["dispatcharr", "other"]
        assert captured["url"] == "http://channels:8089/devices"

    def test_handles_lowercase_keys(self, monkeypatch):
        # Defensive: tolerate lowercase field names if a fork ever ships them.
        def fake_get(url, **kwargs):
            req = httpx.Request("GET", url)
            return httpx.Response(
                200,
                json=[{"provider": "m3u", "friendlyName": "alt"}],
                request=req,
            )

        monkeypatch.setattr(httpx, "get", fake_get)

        client = ChannelsDVRClient(base_url="http://channels:8089")
        result = client.list_m3u_sources()
        assert result["sources"] == ["alt"]

    def test_falls_back_to_name_when_friendlyname_missing(self, monkeypatch):
        def fake_get(url, **kwargs):
            req = httpx.Request("GET", url)
            return httpx.Response(
                200,
                json=[{"Provider": "m3u", "Name": "legacy"}],
                request=req,
            )

        monkeypatch.setattr(httpx, "get", fake_get)

        client = ChannelsDVRClient(base_url="http://channels:8089")
        result = client.list_m3u_sources()
        assert result["sources"] == ["legacy"]

    def test_unreachable_returns_error(self, monkeypatch):
        def fake_get(url, **kwargs):
            raise httpx.ConnectError("conn refused")

        monkeypatch.setattr(httpx, "get", fake_get)

        client = ChannelsDVRClient(base_url="http://channels:8089")
        result = client.list_m3u_sources()
        assert result["success"] is False
        assert result["sources"] == []


class TestListLineups:
    def test_returns_id_and_name(self, monkeypatch):
        # /dvr/lineups returns every guide lineup with at least an ID; the
        # ID is what the refresh PUT path expects.
        captured: dict = {}

        def fake_get(url, **kwargs):
            captured["url"] = url
            req = httpx.Request("GET", url)
            payload = [
                {"ID": "XMLTV-dispatcharr", "Name": "Dispatcharr Guide"},
                {"ID": "Gracenote", "Name": "Gracenote (USA)"},
            ]
            return httpx.Response(200, json=payload, request=req)

        monkeypatch.setattr(httpx, "get", fake_get)

        client = ChannelsDVRClient(base_url="http://channels:8089")
        result = client.list_lineups()

        assert result["success"] is True
        assert result["lineups"] == [
            {"id": "XMLTV-dispatcharr", "name": "Dispatcharr Guide"},
            {"id": "Gracenote", "name": "Gracenote (USA)"},
        ]
        assert captured["url"] == "http://channels:8089/dvr/lineups"

    def test_falls_back_to_name_when_id_missing(self, monkeypatch):
        # Some lineups only expose Name; treat Name as the ID in that case.
        def fake_get(url, **kwargs):
            req = httpx.Request("GET", url)
            return httpx.Response(200, json=[{"Name": "XMLTV-only"}], request=req)

        monkeypatch.setattr(httpx, "get", fake_get)

        client = ChannelsDVRClient(base_url="http://channels:8089")
        result = client.list_lineups()
        assert result["lineups"] == [{"id": "XMLTV-only", "name": "XMLTV-only"}]

    def test_dict_format_source_to_lineup_map(self, monkeypatch):
        # CDVR actually returns {source_id: lineup_id} — values are the IDs
        # we PUT to /dvr/lineups/<lineup_id>. Observed in the wild:
        # {"10A11DAC":"USA-OTA48009","M3U-dispatcharr":"XMLTV-dispatcharr",...}
        def fake_get(url, **kwargs):
            req = httpx.Request("GET", url)
            payload = {
                "10A11DAC": "USA-OTA48009",
                "2022-09-I5DK-8H4GRQ:3": "XMLTV-CUSTOM",
                "M3U-dispatcharr": "XMLTV-dispatcharr",
                "VIRTUAL": "X-VIRTUAL",
            }
            return httpx.Response(200, json=payload, request=req)

        monkeypatch.setattr(httpx, "get", fake_get)

        client = ChannelsDVRClient(base_url="http://channels:8089")
        result = client.list_lineups()

        assert result["success"] is True
        ids = {lineup["id"] for lineup in result["lineups"]}
        assert ids == {"USA-OTA48009", "XMLTV-CUSTOM", "XMLTV-dispatcharr", "X-VIRTUAL"}

    def test_unreachable_returns_error(self, monkeypatch):
        def fake_get(url, **kwargs):
            raise httpx.ConnectError("conn refused")

        monkeypatch.setattr(httpx, "get", fake_get)

        client = ChannelsDVRClient(base_url="http://channels:8089")
        result = client.list_lineups()
        assert result["success"] is False
        assert result["lineups"] == []


class TestTriggerEPGRefresh:
    def test_no_lineup_returns_failure(self):
        client = ChannelsDVRClient(base_url="http://channels:8089")
        result = client.trigger_epg_refresh()
        assert result["success"] is False
        assert "lineup" in result["message"].lower()

    def test_successful_refresh_uses_put(self, monkeypatch):
        # Pin the verb (PUT) and URL — the working-script reference is
        # `PUT /dvr/lineups/XMLTV-{name}`, anything else returns 404.
        captured: dict = {}

        def fake_put(url, **kwargs):
            captured["url"] = url
            req = httpx.Request("PUT", url)
            return httpx.Response(200, request=req)

        monkeypatch.setattr(httpx, "put", fake_put)

        client = ChannelsDVRClient(base_url="http://channels:8089", lineup_id="XMLTV-dispatcharr")
        result = client.trigger_epg_refresh()

        assert result["success"] is True
        assert captured["url"] == "http://channels:8089/dvr/lineups/XMLTV-dispatcharr"

    def test_url_encodes_lineup_id(self, monkeypatch):
        captured: dict = {}

        def fake_put(url, **kwargs):
            captured["url"] = url
            req = httpx.Request("PUT", url)
            return httpx.Response(200, request=req)

        monkeypatch.setattr(httpx, "put", fake_put)

        client = ChannelsDVRClient(base_url="http://channels:8089", lineup_id="My Lineup/Slash")
        client.trigger_epg_refresh()

        assert captured["url"] == "http://channels:8089/dvr/lineups/My%20Lineup%2FSlash"

    def test_404_returns_lineup_not_found(self, monkeypatch):
        def fake_put(url, **kwargs):
            req = httpx.Request("PUT", url)
            return httpx.Response(404, request=req)

        monkeypatch.setattr(httpx, "put", fake_put)

        client = ChannelsDVRClient(base_url="http://channels:8089", lineup_id="missing")
        result = client.trigger_epg_refresh()

        assert result["success"] is False
        assert "not found" in result["message"].lower()


def _sequenced_get(before: str, after: str):
    """httpx.get fake: 1st call (the pre-request watermark) sees ``before``,
    every later call (the poll loop) sees ``after`` — so a line present only
    in ``after`` is detected as newer than the watermark."""
    calls = {"n": 0}

    def fake_get(url, **kwargs):
        calls["n"] += 1
        body = before if calls["n"] == 1 else after
        return httpx.Response(200, text=body, request=httpx.Request("GET", url))

    return fake_get


def _ok_post(url, **kwargs):
    return httpx.Response(200, json=True, request=httpx.Request("POST", url))


def _ok_put(url, **kwargs):
    return httpx.Response(200, request=httpx.Request("PUT", url))


# Short builders for the CDVR /log lines our pollers match, to keep literals
# under the line-length limit and document the exact real-world format.
def _m3u(ts, src="dispatcharr", n=100):
    return f"{ts} [M3U] Refreshed lineup for {src} with {n} channels\n"


def _fetched(ts, lineup="XMLTV-dispatcharr"):
    return f"{ts} [DVR] Fetched guide data for {lineup} in 2s\n"


def _indexed(ts, n, lineup="XMLTV-dispatcharr"):
    return (
        f"{ts} [DVR] Indexed {n} airings into {lineup} "
        "(161 channels over 345h0m0s) + 0 skipped [15s index]\n"
    )


def _prune(ts, lineup="XMLTV-dispatcharr"):
    return f"{ts} [IDX] Pruned 0 expired groups from {lineup} in 1ms.\n"


class TestM3UWaitForCompletion:
    """trigger_m3u_refresh(wait_for_completion=True) gates on real /log evidence."""

    def setup_method(self):
        # Tiny ceilings so the timeout branch resolves fast; never sleep for real.
        self._orig = (
            ChannelsDVRClient.M3U_COMPLETION_TIMEOUT,
            ChannelsDVRClient.LOG_POLL_INTERVAL,
        )
        ChannelsDVRClient.M3U_COMPLETION_TIMEOUT = 0.2
        ChannelsDVRClient.LOG_POLL_INTERVAL = 0.0

    def teardown_method(self):
        (
            ChannelsDVRClient.M3U_COMPLETION_TIMEOUT,
            ChannelsDVRClient.LOG_POLL_INTERVAL,
        ) = self._orig

    def test_completion_confirmed_when_new_refresh_line_appears(self, monkeypatch):
        before = _m3u("2026/06/15 16:00:00.000000", n=100)
        after = before + _m3u("2026/06/15 16:06:04.383076", n=164)
        monkeypatch.setattr(httpx, "get", _sequenced_get(before, after))
        monkeypatch.setattr(httpx, "post", _ok_post)
        monkeypatch.setattr(time, "sleep", lambda *_: None)

        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="dispatcharr")
        result = client.trigger_m3u_refresh(wait_for_completion=True)

        assert result["success"] is True
        assert result["completed"] is True

    def test_completion_unconfirmed_when_no_new_line(self, monkeypatch):
        # Only a stale line (older than/equal to the watermark) — never newer.
        log = _m3u("2026/06/15 16:00:00.000000", n=100)
        monkeypatch.setattr(httpx, "get", _sequenced_get(log, log))
        monkeypatch.setattr(httpx, "post", _ok_post)
        monkeypatch.setattr(time, "sleep", lambda *_: None)

        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="dispatcharr")
        result = client.trigger_m3u_refresh(wait_for_completion=True)

        assert result["success"] is True
        assert result["completed"] is False

    def test_other_source_line_does_not_count(self, monkeypatch):
        before = ""
        after = _m3u("2026/06/15 16:06:04.383076", src="othersource", n=9)
        monkeypatch.setattr(httpx, "get", _sequenced_get(before, after))
        monkeypatch.setattr(httpx, "post", _ok_post)
        monkeypatch.setattr(time, "sleep", lambda *_: None)

        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="dispatcharr")
        result = client.trigger_m3u_refresh(wait_for_completion=True)

        assert result["completed"] is False

    def test_log_unreachable_reports_none(self, monkeypatch):
        def boom(url, **kwargs):
            raise httpx.ConnectError("no log")

        monkeypatch.setattr(httpx, "get", boom)
        monkeypatch.setattr(httpx, "post", _ok_post)
        monkeypatch.setattr(time, "sleep", lambda *_: None)

        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="dispatcharr")
        result = client.trigger_m3u_refresh(wait_for_completion=True)

        assert result["success"] is True
        assert result["completed"] is None

    def test_not_awaited_by_default(self, monkeypatch):
        monkeypatch.setattr(httpx, "post", _ok_post)
        # No httpx.get fake — if it polled /log this would error.
        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="dispatcharr")
        result = client.trigger_m3u_refresh()

        assert result["success"] is True
        assert "completed" not in result


class TestEPGVerify:
    """trigger_epg_refresh(verify=True) confirms the guide actually re-indexed."""

    def setup_method(self):
        self._orig = (
            ChannelsDVRClient.GUIDE_FETCH_TIMEOUT,
            ChannelsDVRClient.GUIDE_INDEX_TIMEOUT,
            ChannelsDVRClient.LOG_POLL_INTERVAL,
        )
        ChannelsDVRClient.GUIDE_FETCH_TIMEOUT = 0.2
        ChannelsDVRClient.GUIDE_INDEX_TIMEOUT = 0.2
        ChannelsDVRClient.LOG_POLL_INTERVAL = 0.0

    def teardown_method(self):
        (
            ChannelsDVRClient.GUIDE_FETCH_TIMEOUT,
            ChannelsDVRClient.GUIDE_INDEX_TIMEOUT,
            ChannelsDVRClient.LOG_POLL_INTERVAL,
        ) = self._orig

    def test_indexed_reports_airings(self, monkeypatch):
        before = _prune("2026/06/15 16:00:00.000000")
        after = (
            before
            + _fetched("2026/06/15 16:06:06.605869")
            + _indexed("2026/06/15 16:06:22.330813", 34216)
        )
        monkeypatch.setattr(httpx, "get", _sequenced_get(before, after))
        monkeypatch.setattr(httpx, "put", _ok_put)
        monkeypatch.setattr(time, "sleep", lambda *_: None)

        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="dispatcharr")
        result = client.trigger_epg_refresh(verify=True)

        assert result["verified"] is True
        assert result["verification"]["status"] == "indexed"
        assert result["verification"]["airings"] == 34216

    def test_no_fetch_is_failure(self, monkeypatch):
        log = _prune("2026/06/15 16:00:00.000000")
        monkeypatch.setattr(httpx, "get", _sequenced_get(log, log))
        monkeypatch.setattr(httpx, "put", _ok_put)
        monkeypatch.setattr(time, "sleep", lambda *_: None)

        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="dispatcharr")
        result = client.trigger_epg_refresh(verify=True)

        assert result["success"] is True  # request was accepted
        assert result["verified"] is False
        assert result["verification"]["status"] == "no_fetch"

    def test_fetched_without_index(self, monkeypatch):
        before = _prune("2026/06/15 16:00:00.000000")
        after = before + _fetched("2026/06/15 16:06:06.605869")
        monkeypatch.setattr(httpx, "get", _sequenced_get(before, after))
        monkeypatch.setattr(httpx, "put", _ok_put)
        monkeypatch.setattr(time, "sleep", lambda *_: None)

        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="dispatcharr")
        result = client.trigger_epg_refresh(verify=True)

        assert result["verified"] is True
        assert result["verification"]["status"] == "fetched"

    def test_log_unreachable_is_unverifiable(self, monkeypatch):
        def boom(url, **kwargs):
            raise httpx.ConnectError("no log")

        monkeypatch.setattr(httpx, "get", boom)
        monkeypatch.setattr(httpx, "put", _ok_put)
        monkeypatch.setattr(time, "sleep", lambda *_: None)

        client = ChannelsDVRClient(base_url="http://channels:8089", source_name="dispatcharr")
        result = client.trigger_epg_refresh(verify=True)

        assert result["success"] is True
        assert result["verified"] is None
        assert result["verification"]["status"] == "unverifiable"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
