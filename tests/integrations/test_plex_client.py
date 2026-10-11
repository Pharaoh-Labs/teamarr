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
    device_read_problem,
    guide_path_from_lineup,
    is_complete_xmltv,
    parse_enabled,
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
    """Union core — a channel Teamarr does not own can never be disabled."""

    def test_preserves_foreign_channels_at_any_number(self):
        """The old range model claimed everything >= channel_range_start, so a
        default install disabled foreign channels at 150 and team channels at
        9000. Nothing is owned by number any more."""
        current = [
            PlexChannelMapping(device_identifier=k, enabled=True, lineup_identifier=k)
            for k in ("5", "150", "9000")
        ]
        enabled, mapping = compute_channelmap_update(current, {"101"})

        assert set(enabled) == {"5", "150", "9000", "101"}
        assert mapping["150"] == "150"
        assert mapping["9000"] == "9000"

    def test_mapping_covers_every_enabled_channel(self):
        """A channel in channelsEnabled but missing from the mapping params is
        disabled anyway (live-tested), so the mapping is not a delta."""
        current = [
            PlexChannelMapping(device_identifier="700", enabled=True, lineup_identifier="700")
        ]
        enabled, mapping = compute_channelmap_update(current, {"101"})
        assert set(mapping) == set(enabled)

    def test_preserved_channel_keeps_its_own_epg_binding(self):
        current = [
            PlexChannelMapping(device_identifier="700", enabled=True, lineup_identifier="101")
        ]
        _, mapping = compute_channelmap_update(current, set())
        assert mapping["700"] == "101"

    def test_disabled_channels_stay_disabled(self):
        current = [
            PlexChannelMapping(device_identifier="60", enabled=False, lineup_identifier="60")
        ]
        enabled, _ = compute_channelmap_update(current, set())
        assert enabled == []

    def test_previously_pushed_channel_no_longer_ours_is_dropped(self):
        """The only removal path: we pushed 101 before and no longer have it."""
        current = [
            PlexChannelMapping(device_identifier="101", enabled=True, lineup_identifier="101"),
            PlexChannelMapping(device_identifier="700", enabled=True, lineup_identifier="700"),
        ]
        enabled, _ = compute_channelmap_update(
            current, {"102"}, previously_pushed={"101"}
        )
        assert set(enabled) == {"102", "700"}

    def test_previously_pushed_cannot_remove_a_foreign_channel(self):
        """Even a stored set that wrongly names a foreign channel only removes
        it if Teamarr also no longer claims it — and it was never claimed."""
        current = [
            PlexChannelMapping(device_identifier="700", enabled=True, lineup_identifier="700")
        ]
        enabled, _ = compute_channelmap_update(current, {"700"}, previously_pushed={"700"})
        assert enabled == ["700"]

    def test_team_channels_are_kept_when_managed(self):
        current = [
            PlexChannelMapping(device_identifier="9000", enabled=True, lineup_identifier="9000")
        ]
        enabled, _ = compute_channelmap_update(current, {"9000"})
        assert enabled == ["9000"]

    def test_non_numeric_identifier_survives(self):
        current = [
            PlexChannelMapping(device_identifier="abc", enabled=True, lineup_identifier="abc")
        ]
        enabled, _ = compute_channelmap_update(current, set())
        assert enabled == ["abc"]

    def test_empty_current_and_no_channels(self):
        enabled, mapping = compute_channelmap_update([], set())
        assert enabled == [] and mapping == {}


class TestParseEnabled:
    """Unknown shapes must fail toward preserving, never toward disabling."""

    @pytest.mark.parametrize("raw", ["1", 1, True, "true", "TRUE", "yes", "on"])
    def test_truthy(self, raw):
        assert parse_enabled(raw) is True

    @pytest.mark.parametrize("raw", ["0", 0, False, "false", "no", "off", "", None])
    def test_falsey(self, raw):
        assert parse_enabled(raw) is False

    @pytest.mark.parametrize("raw", ["weird", 7, object()])
    def test_unknown_defaults_to_enabled(self, raw):
        assert parse_enabled(raw) is True


class TestDeviceReadProblem:
    def test_clean_read_is_fine(self):
        dev = PlexDevice(key="54", channel_mapping=[
            PlexChannelMapping(device_identifier="1", enabled=True)
        ])
        assert device_read_problem(dev, expect_channels=True) is None

    def test_null_device_identifier_is_refused(self):
        dev = PlexDevice(key="54", channel_mapping=[
            PlexChannelMapping(device_identifier="None", enabled=True)
        ])
        assert "deviceIdentifier" in device_read_problem(dev, expect_channels=False)

    def test_empty_mapping_refused_only_when_previously_populated(self):
        dev = PlexDevice(key="54", channel_mapping=[])
        assert device_read_problem(dev, expect_channels=True) is not None
        assert device_read_problem(dev, expect_channels=False) is None


class TestGuidePathFromLineup:
    def test_extracts_path_and_query(self):
        lineup = (
            "lineup://tv.plex.providers.epg.xmltv/"
            "http%3A%2F%2Flocalhost%3A9191%2Foutput%2Fepg%2FNFL%3Fcachedlogos%3Dfalse"
            "#NFL%20Guide"
        )
        assert guide_path_from_lineup(lineup) == "/output/epg/NFL?cachedlogos=false"

    def test_no_query(self):
        lineup = "lineup://tv.plex.providers.epg.xmltv/http%3A%2F%2Fd%3A9191%2Foutput%2Fepg#T"
        assert guide_path_from_lineup(lineup) == "/output/epg"

    @pytest.mark.parametrize("lineup", [None, "", "lineup://other/x", "not a lineup"])
    def test_unrecognised_returns_none(self, lineup):
        assert guide_path_from_lineup(lineup) is None


class TestIsCompleteXmltv:
    def test_whole_document(self):
        assert is_complete_xmltv(b'<?xml version="1.0"?><tv><programme channel="7"/></tv>')

    def test_truncated_mid_programme(self):
        assert not is_complete_xmltv(b'<tv>\n  <programme start="2026" channel="7')

    def test_extra_content_after_root(self):
        assert not is_complete_xmltv(b"<tv></tv><programme/>")

    def test_wrong_root_or_empty(self):
        assert not is_complete_xmltv(b"<html></html>")
        assert not is_complete_xmltv(b"")
