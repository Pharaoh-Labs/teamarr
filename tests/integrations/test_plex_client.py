"""Tests for PlexClient and the fetch-merge-write channelmap logic.

The channelmap PUT is a full-state-replace (Plex Web always sends the
complete enabled-channel set, never a delta), so `compute_channelmap_update`
is the safety-critical part of this integration: it must never drop a
channel that isn't Teamarr's own. These tests pin that contract, plus URL
building and HTTP method/param handling.

Everything is keyed on `device_identifier` (the stable Dispatcharr/
HDHomeRun physical channel number), never `channel_key` (Plex's mutable,
currently-matched EPG guide channel — verified against a live server to
diverge from the physical channel after a manual Channel Matching remap).
"""

import httpx
import pytest

from teamarr.plex.client import (
    PlexChannelMapping,
    PlexClient,
    PlexDevice,
    compute_channelmap_update,
)


class TestUrlBuilding:
    def test_strips_trailing_slash(self):
        client = PlexClient(base_url="http://plex:32400/", token="abc")
        assert client.base_url == "http://plex:32400"


class TestProfileHint:
    def test_scoped_uri_returns_last_segment(self):
        device = PlexDevice(key="54", uri="http://dispatcharr:9191/hdhr/NFL")
        assert device.profile_hint == "NFL"

    def test_root_scoped_uri_returns_none(self):
        device = PlexDevice(key="20", uri="http://dispatcharr:9191/hdhr")
        assert device.profile_hint is None

    def test_no_uri_returns_none(self):
        device = PlexDevice(key="1", uri=None)
        assert device.profile_hint is None


class TestListDvrsHTTP:
    def test_parses_dvrs_devices_and_channel_mapping(self, monkeypatch):
        def fake_get(url, **kwargs):
            assert kwargs["headers"]["X-Plex-Token"] == "abc"
            req = httpx.Request("GET", url)
            body = {
                "MediaContainer": {
                    "Dvr": [
                        {
                            "key": "52",
                            "lineupTitle": "Dispatcharr",
                            "Device": [
                                {
                                    "key": "54",
                                    "deviceId": "dispatcharr-hdhr-NFL",
                                    "uri": "http://dispatcharr:9191/hdhr/NFL",
                                    "ChannelMapping": [
                                        {
                                            "channelKey": "301",
                                            "deviceIdentifier": "301",
                                            "enabled": "1",
                                            "lineupIdentifier": "301",
                                        },
                                        {
                                            "channelKey": "60",
                                            "deviceIdentifier": "60",
                                            "enabled": "0",
                                            "lineupIdentifier": "60",
                                        },
                                    ],
                                }
                            ],
                        }
                    ]
                }
            }
            return httpx.Response(200, json=body, request=req)

        monkeypatch.setattr(httpx, "get", fake_get)

        client = PlexClient(base_url="http://plex:32400", token="abc")
        result = client.list_dvrs()

        assert result["success"] is True
        dvr = result["dvrs"][0]
        assert dvr.key == "52"
        device = dvr.devices[0]
        assert device.key == "54"
        assert device.profile_hint == "NFL"
        assert len(device.channel_mapping) == 2
        assert device.channel_mapping[0].enabled is True
        assert device.channel_mapping[1].enabled is False

    def test_channel_key_and_device_identifier_can_diverge(self, monkeypatch):
        """Pins the live-server finding: a Plex Channel Matching remap moves
        `channelKey` to track the newly-matched EPG entry while
        `deviceIdentifier` stays fixed at the physical channel. Teamarr must
        key on `deviceIdentifier`, never `channelKey`."""

        def fake_get(url, **kwargs):
            req = httpx.Request("GET", url)
            body = {
                "MediaContainer": {
                    "Dvr": [
                        {
                            "key": "55",
                            "Device": [
                                {
                                    "key": "54",
                                    "ChannelMapping": [
                                        {
                                            "channelKey": "101",
                                            "deviceIdentifier": "700",
                                            "enabled": "1",
                                            "lineupIdentifier": "101",
                                        }
                                    ],
                                }
                            ],
                        }
                    ]
                }
            }
            return httpx.Response(200, json=body, request=req)

        monkeypatch.setattr(httpx, "get", fake_get)

        client = PlexClient(base_url="http://plex:32400", token="abc")
        result = client.list_dvrs()

        m = result["dvrs"][0].devices[0].channel_mapping[0]
        assert m.device_identifier == "700"
        assert m.channel_key == "101"
        assert m.lineup_identifier == "101"

    def test_401_returns_invalid_token_error(self, monkeypatch):
        def fake_get(url, **kwargs):
            req = httpx.Request("GET", url)
            return httpx.Response(401, request=req)

        monkeypatch.setattr(httpx, "get", fake_get)

        client = PlexClient(base_url="http://plex:32400", token="bad")
        result = client.list_dvrs()

        assert result["success"] is False
        assert "token" in result["error"].lower()


class TestUpdateChannelmap:
    def test_puts_full_enabled_set_and_mapping_params(self, monkeypatch):
        captured = {}

        def fake_put(url, **kwargs):
            captured["url"] = url
            captured["params"] = kwargs["params"]
            req = httpx.Request("PUT", url)
            return httpx.Response(200, request=req)

        monkeypatch.setattr(httpx, "put", fake_put)

        client = PlexClient(base_url="http://plex:32400", token="abc")
        result = client.update_channelmap(
            "54", ["60", "301"], {"60": "60", "301": "301"}
        )

        assert result["success"] is True
        assert captured["url"] == "http://plex:32400/media/grabbers/devices/54/channelmap"
        params = dict(captured["params"])
        assert params["channelsEnabled"] == "60,301"
        assert params["channelMappingByKey[60]"] == "60"
        assert params["channelMappingByKey[301]"] == "301"
        assert params["channelMapping[60]"] == "60"
        assert params["channelMapping[301]"] == "301"

    def test_channel_mapping_by_key_matches_resolved_value_not_identity(self, monkeypatch):
        """A preserved foreign channel's EPG binding can differ from its
        channel number — both params must agree on the real value, not
        silently disagree (previously channelMappingByKey always sent the
        key back as its own value)."""
        captured = {}

        def fake_put(url, **kwargs):
            captured["params"] = kwargs["params"]
            req = httpx.Request("PUT", url)
            return httpx.Response(200, request=req)

        monkeypatch.setattr(httpx, "put", fake_put)

        client = PlexClient(base_url="http://plex:32400", token="abc")
        client.update_channelmap("54", ["700"], {"700": "101"})

        params = dict(captured["params"])
        assert params["channelMappingByKey[700]"] == "101"
        assert params["channelMapping[700]"] == "101"


class TestComputeChannelmapUpdate:
    """The fetch-merge-write core — must never drop non-Teamarr channels."""

    def test_preserves_channels_outside_teamarr_range(self):
        current = [
            PlexChannelMapping(device_identifier="60", enabled=True, lineup_identifier="60"),
            PlexChannelMapping(device_identifier="90", enabled=True, lineup_identifier="90"),
        ]
        enabled, mapping = compute_channelmap_update(
            current, teamarr_channel_keys={"101", "102"}, teamarr_range=(101, 200)
        )

        assert set(enabled) == {"60", "90", "101", "102"}
        assert mapping["60"] == "60"
        assert mapping["90"] == "90"
        assert mapping["101"] == "101"
        assert mapping["102"] == "102"

    def test_disabled_non_teamarr_channels_stay_disabled(self):
        current = [
            PlexChannelMapping(device_identifier="60", enabled=False, lineup_identifier="60"),
        ]
        enabled, _ = compute_channelmap_update(
            current, teamarr_channel_keys=set(), teamarr_range=(101, 200)
        )
        assert enabled == []

    def test_removed_teamarr_channel_drops_out(self):
        """A Teamarr channel no longer present isn't re-added just because
        it's still enabled in Plex's last-known state — the caller passes
        only currently-active channel numbers."""
        current = [
            PlexChannelMapping(device_identifier="101", enabled=True, lineup_identifier="101"),
        ]
        enabled, mapping = compute_channelmap_update(
            current, teamarr_channel_keys={"102"}, teamarr_range=(101, 200)
        )
        # 101 is inside Teamarr's range and not in the current active set,
        # so it's dropped; 102 (active) is added.
        assert set(enabled) == {"102"}
        assert "101" not in mapping

    def test_root_scoped_device_no_range_preserves_nothing_owned(self):
        """No range configured means nothing is recognized as Teamarr's own
        (defensive default) — every enabled channel from another tool is
        still preserved since none are (falsely) claimed as Teamarr range."""
        current = [
            PlexChannelMapping(device_identifier="5", enabled=True, lineup_identifier="5"),
        ]
        enabled, mapping = compute_channelmap_update(
            current, teamarr_channel_keys={"101"}, teamarr_range=None
        )
        assert set(enabled) == {"5", "101"}
        assert mapping["5"] == "5"

    def test_unbounded_range_end_none(self):
        current = [
            PlexChannelMapping(device_identifier="50", enabled=True, lineup_identifier="50"),
            PlexChannelMapping(device_identifier="150", enabled=True, lineup_identifier="150"),
        ]
        enabled, _ = compute_channelmap_update(
            current, teamarr_channel_keys={"200"}, teamarr_range=(101, None)
        )
        # 50 is outside the range (preserved), 150 is inside but no longer
        # active (dropped), 200 is the active Teamarr channel (added).
        assert set(enabled) == {"50", "200"}

    def test_non_numeric_channel_key_is_never_treated_as_owned(self):
        current = [
            PlexChannelMapping(device_identifier="abc", enabled=True, lineup_identifier="abc"),
        ]
        enabled, _ = compute_channelmap_update(
            current, teamarr_channel_keys=set(), teamarr_range=(101, 200)
        )
        assert enabled == ["abc"]

    def test_preserved_channel_keeps_its_own_epg_binding(self):
        """A foreign channel's EPG match may differ from its channel number
        (Plex's Channel Matching UI allows remapping) — the preserved
        mapping must carry that real binding forward, not force identity.
        And it must be present at all: a channel in `channelsEnabled` but
        missing from the mapping gets disabled anyway (confirmed on a live
        server, 2026-09-12) — there's no safe way to omit "unchanged"
        channels from the mapping to avoid resending them."""
        current = [
            PlexChannelMapping(
                device_identifier="700", enabled=True, lineup_identifier="101"
            ),
        ]
        enabled, mapping = compute_channelmap_update(
            current, teamarr_channel_keys=set(), teamarr_range=(101, 200)
        )
        assert enabled == ["700"]
        assert mapping["700"] == "101"

    @pytest.mark.parametrize("range_", [(101, 200), (101, None), None])
    def test_never_raises_on_empty_current(self, range_):
        enabled, mapping = compute_channelmap_update([], {"101"}, range_)
        assert enabled == ["101"]
        assert mapping == {"101": "101"}
