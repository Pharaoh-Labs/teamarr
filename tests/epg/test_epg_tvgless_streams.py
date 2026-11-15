"""A stream with no tvg-id still reaches the guide (#1215).

The guide lookup can identify a stream three ways — its Dispatcharr channel,
its own tvg-id, a strict name match — and only the second needs a tvg-id on the
stream. But the whole EPG path was keyed on the stream tvg-id, so a stream
without one was dropped before the other two were tried: reported as
``4K: Sportsnet ONE`` reading "stream carries no tvg-id" while the user's player
showed a full guide for it. ``_build_epg_index`` also returned an empty index
when NO stream in the source carried one.

The resolver tests pin the borrowing rule itself; these pin the index builder
around it.
"""

from datetime import date
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from teamarr.consumers.event_group_processor import matching as matching_mod
from teamarr.consumers.event_group_processor.matching import StreamMatching
from teamarr.consumers.matching.epg_index import EPGProgramIndex
from teamarr.consumers.matching.epg_resolver import BORROWED_TVG_ID_KEY

TARGET = date(2026, 11, 12)
EPG_DATA = [{"id": 1, "tvg_id": "SportsnetOne.ca", "name": "Sportsnet ONE HD", "epg_source": 7}]


class _Harness(StreamMatching):
    def __init__(self, stream_channels):
        self._dispatcharr_client = SimpleNamespace(epg=object())
        self._stream_channels = stream_channels
        self.xtream_wanted: list[set] = []

    def _epg_resolution_inputs(self):
        return SimpleNamespace(
            epg_data_list=EPG_DATA,
            stream_channels=self._stream_channels,
            active_source_ids={7},
            channel_by_uuid={},
            own_source_id=None,
            catalog=None,
        )


def _capture_build(monkeypatch) -> dict:
    seen: dict = {}

    def fake_build(_epg, resolution, _start, _end):
        seen["resolution"] = dict(resolution)
        return EPGProgramIndex({})

    monkeypatch.setattr(EPGProgramIndex, "build", staticmethod(fake_build))
    monkeypatch.setattr(matching_mod, "get_user_timezone", lambda: ZoneInfo("UTC"))
    return seen


def test_source_with_no_tvg_ids_at_all_still_resolves_through_the_channel(monkeypatch):
    seen = _capture_build(monkeypatch)
    group = SimpleNamespace(id=125, epg_match_enabled=True)
    streams = [{"id": 10, "name": "4K: Sportsnet ONE", "tvg_id": None}]

    index = _Harness({10: {"epg_data_id": 1}})._build_epg_index(group, streams, TARGET, 3)

    assert index is not None
    assert seen["resolution"] == {"SportsnetOne.ca": "SportsnetOne.ca"}
    # The matcher reads the key off the same dict it is handed.
    assert streams[0]["tvg_id"] == "SportsnetOne.ca"


def test_source_with_nothing_to_resolve_gets_an_empty_index_not_none(monkeypatch):
    """#877: an opted-in group never gets None; each stream lands on no_epg_channel."""
    seen = _capture_build(monkeypatch)
    group = SimpleNamespace(id=125, epg_match_enabled=True)
    streams = [{"id": 10, "name": "Nothing Like It", "tvg_id": None}]

    index = _Harness({})._build_epg_index(group, streams, TARGET, 3)

    assert index is not None and not index
    assert getattr(index, "unavailable", None) is None
    assert "resolution" not in seen  # nothing resolved, nothing fetched
    assert streams[0]["tvg_id"] is None


def test_provider_guide_fallback_is_not_offered_a_borrowed_id(monkeypatch):
    """The Xtream fallback matches the provider's OWN ids; a borrowed id is
    the Dispatcharr guide's and must not be looked up there."""
    _capture_build(monkeypatch)
    wanted_seen: list[set] = []

    def fake_fetch(_url, *, cache_key, wanted_tvg_ids, window_start, window_end, ttl_seconds):
        wanted_seen.append(set(wanted_tvg_ids))
        return {}

    monkeypatch.setattr("teamarr.consumers.matching.epg_xtream.fetch_xtream_programs", fake_fetch)
    monkeypatch.setattr("teamarr.consumers.matching.epg_xtream.is_xtream_account", lambda a: True)
    monkeypatch.setattr("teamarr.consumers.matching.epg_xtream.xmltv_url", lambda a: "http://x")

    h = _Harness({10: {"epg_data_id": 1}})
    h._dispatcharr_client.client = SimpleNamespace(
        get=lambda _path: SimpleNamespace(status_code=200, json=lambda: {"id": 3})
    )
    group = SimpleNamespace(id=125, epg_match_enabled=True, m3u_account_id=3)
    streams = [
        {"id": 10, "name": "4K: Sportsnet ONE", "tvg_id": None},
        {"id": 11, "name": "4K: ESPN", "tvg_id": "ESPN.us"},
    ]

    h._build_epg_index(group, streams, TARGET, 3, xtream_fallback=True)

    assert streams[0][BORROWED_TVG_ID_KEY] is True
    assert wanted_seen == [{"ESPN.us"}]
