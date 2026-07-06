"""Tests for the Dispatcharr-channels EPG source (epic teamarrv2-183.9).

Covers EventGroupProcessor._fetch_channel_source_streams: building EPG-match
candidates from streams curated onto Dispatcharr channels, with the right
exclusions (Teamarr's own output channels, channels without an active EPG link)
and dedupe (streams already owned by an EPG-match-enabled M3U group).
"""

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from teamarr.consumers.event_group_processor import EventGroupProcessor
from teamarr.database.connection import get_connection, init_db
from teamarr.database.groups import (
    ensure_channel_source_group,
    get_all_groups,
    get_group,
)


def _stream(sid, name, group_id=None):
    return SimpleNamespace(
        id=sid,
        name=name,
        tvg_id="",  # raw streams carry empty tvg_id; the channel EPG drives matching
        tvg_name=None,
        channel_group=None,
        channel_group_id=group_id,
        m3u_account_id=7,
        is_stale=False,
    )


def _make_processor(stream_channel_map, epg_data_list, streams, managed, epg_groups, monkeypatch):
    """Build a processor with mocked Dispatcharr client + DB lookups."""
    client = SimpleNamespace(
        channels=SimpleNamespace(
            get_stream_channel_map=lambda: stream_channel_map,
            get_epg_data_list=lambda: epg_data_list,
        ),
        m3u=SimpleNamespace(list_streams=lambda: streams),
    )

    proc = object.__new__(EventGroupProcessor)
    proc._dispatcharr_client = client

    @contextmanager
    def _db():
        yield None

    proc._db_factory = _db
    proc._active_epg_source_ids = lambda: {10}  # only source id 10 is active

    monkeypatch.setattr(
        "teamarr.database.channels.get_all_managed_channels",
        lambda conn, include_deleted=False: managed,
    )
    monkeypatch.setattr(
        "teamarr.database.groups.get_all_groups",
        lambda conn, include_disabled=False: epg_groups,
    )
    return proc


def test_builds_candidates_tagged_with_channel_epg_tvgid(monkeypatch):
    # Channel 100 (epg_data_id 1 -> tvg 'ESPN.us', active source 10) carries stream 500.
    proc = _make_processor(
        stream_channel_map={500: {"id": 100, "epg_data_id": 1, "name": "ESPN"}},
        epg_data_list=[{"id": 1, "tvg_id": "ESPN.us", "epg_source": 10}],
        streams=[_stream(500, "ESPN HD", group_id=42)],
        managed=[],
        epg_groups=[],
        monkeypatch=monkeypatch,
    )
    out = proc._fetch_channel_source_streams()
    assert len(out) == 1
    assert out[0]["id"] == 500
    # Tagged with the CHANNEL's EPG tvg_id (not the empty stream tvg_id).
    assert out[0]["tvg_id"] == "ESPN.us"


def test_excludes_teamarr_managed_channels(monkeypatch):
    # Stream 500 is on Dispatcharr channel 100, which is a Teamarr OUTPUT channel.
    proc = _make_processor(
        stream_channel_map={500: {"id": 100, "epg_data_id": 1, "name": "X"}},
        epg_data_list=[{"id": 1, "tvg_id": "ESPN.us", "epg_source": 10}],
        streams=[_stream(500, "ESPN HD")],
        managed=[SimpleNamespace(dispatcharr_channel_id=100)],
        epg_groups=[],
        monkeypatch=monkeypatch,
    )
    assert proc._fetch_channel_source_streams() == []


def test_excludes_channels_without_active_epg(monkeypatch):
    # epg_data_id 2 belongs to inactive source 99; channel 101 has no epg link.
    proc = _make_processor(
        stream_channel_map={
            500: {"id": 100, "epg_data_id": 2, "name": "X"},  # inactive source
            501: {"id": 101, "epg_data_id": None, "name": "Y"},  # no EPG
        },
        epg_data_list=[{"id": 2, "tvg_id": "FS1.us", "epg_source": 99}],
        streams=[_stream(500, "FS1"), _stream(501, "Random")],
        managed=[],
        epg_groups=[],
        monkeypatch=monkeypatch,
    )
    assert proc._fetch_channel_source_streams() == []


def test_dedupes_streams_already_in_epg_match_group(monkeypatch):
    # Stream 500 lives in M3U group 42, which is an EPG-match-enabled event group,
    # so the per-group path already handles it → channel source must skip it.
    epg_group = SimpleNamespace(
        m3u_group_id=42, epg_match_enabled=True, is_channel_source=False
    )
    proc = _make_processor(
        stream_channel_map={500: {"id": 100, "epg_data_id": 1, "name": "ESPN"}},
        epg_data_list=[{"id": 1, "tvg_id": "ESPN.us", "epg_source": 10}],
        streams=[_stream(500, "ESPN HD", group_id=42)],
        managed=[],
        epg_groups=[epg_group],
        monkeypatch=monkeypatch,
    )
    assert proc._fetch_channel_source_streams() == []


def test_keeps_streams_in_non_epg_group(monkeypatch):
    # Same as above but the M3U group is NOT EPG-match-enabled → keep it.
    plain_group = SimpleNamespace(
        m3u_group_id=42, epg_match_enabled=False, is_channel_source=False
    )
    proc = _make_processor(
        stream_channel_map={500: {"id": 100, "epg_data_id": 1, "name": "ESPN"}},
        epg_data_list=[{"id": 1, "tvg_id": "ESPN.us", "epg_source": 10}],
        streams=[_stream(500, "ESPN HD", group_id=42)],
        managed=[],
        epg_groups=[plain_group],
        monkeypatch=monkeypatch,
    )
    out = proc._fetch_channel_source_streams()
    assert [s["id"] for s in out] == [500]


def _two_group_processor(monkeypatch):
    # Channel 100 in DP group 7 (US Sports), channel 101 in group 9 (UK Sports).
    return _make_processor(
        stream_channel_map={
            500: {"id": 100, "epg_data_id": 1, "name": "ESPN",
                  "channel_group_id": 7, "channel_group_name": "US Sports"},
            501: {"id": 101, "epg_data_id": 1, "name": "FS1",
                  "channel_group_id": 9, "channel_group_name": "UK Sports"},
        },
        epg_data_list=[{"id": 1, "tvg_id": "ESPN.us", "epg_source": 10}],
        streams=[_stream(500, "ESPN HD"), _stream(501, "FS1 HD")],
        managed=[],
        epg_groups=[],
        monkeypatch=monkeypatch,
    )


def test_scopes_candidates_to_selected_dp_groups(monkeypatch):
    # Only DP group 7 is selected → only its channel's stream is a candidate (ybt.2).
    proc = _two_group_processor(monkeypatch)
    monkeypatch.setattr(
        "teamarr.database.settings.get_epg_settings",
        lambda conn: SimpleNamespace(epg_channel_source_groups=[7]),
    )
    out = proc._fetch_channel_source_streams()
    assert [s["id"] for s in out] == [500]
    # The DP channel group is stashed for the ordering rule (ybt.3).
    assert out[0]["dp_channel_group_id"] == 7
    assert out[0]["dp_channel_group"] == "US Sports"


def test_empty_selection_includes_all_groups(monkeypatch):
    # Back-compat: empty selection = include all DP groups.
    proc = _two_group_processor(monkeypatch)
    monkeypatch.setattr(
        "teamarr.database.settings.get_epg_settings",
        lambda conn: SimpleNamespace(epg_channel_source_groups=[]),
    )
    out = proc._fetch_channel_source_streams()
    assert sorted(s["id"] for s in out) == [500, 501]


@pytest.fixture
def db(tmp_path: Path):
    db_path = tmp_path / "t.db"
    init_db(db_path)
    conn = get_connection(db_path)
    yield conn
    conn.close()


def test_ensure_channel_source_group_idempotent_and_synced(db):
    gid = ensure_channel_source_group(db, enabled=True)
    g = get_group(db, gid)
    assert g is not None
    assert g.is_channel_source is True
    assert g.epg_match_enabled is True
    assert g.skip_builtin_filter is True
    assert g.enabled is True

    # Second call must not create a duplicate; it syncs the enabled flag.
    gid2 = ensure_channel_source_group(db, enabled=False)
    assert gid2 == gid
    sources = [g for g in get_all_groups(db, include_disabled=True) if g.is_channel_source]
    assert len(sources) == 1
    assert get_group(db, gid).enabled is False


def test_channel_source_group_hidden_from_ui_list(db):
    gid = ensure_channel_source_group(db, enabled=True)
    visible = get_all_groups(db, include_disabled=True, exclude_channel_source=True)
    assert gid not in {g.id for g in visible}
    # Processing path (no exclusion) still sees it.
    everything = get_all_groups(db, include_disabled=True)
    assert gid in {g.id for g in everything}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
