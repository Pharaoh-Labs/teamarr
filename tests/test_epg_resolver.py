"""Tests for the stream -> EPG-source tvg_id resolver (epic teamarrv2-183).

Covers the precedence cascade (direct tvg_id > curated channel > strict name)
and the strict-name guardrails that keep "ESPN" from resolving to "ESPN2".
"""

from teamarr.consumers.matching.epg_resolver import (
    normalize_channel_name,
    resolve_program_tvg_ids,
)


def _epgdata(rows):
    """rows: list of (id, tvg_id, name)."""
    return [{"id": i, "tvg_id": t, "name": n} for i, t, n in rows]


# ================================================================ normalization


def test_normalize_strips_quality_and_punctuation():
    assert normalize_channel_name("beIn Sports Xtra FHD") == "bein sports xtra"
    assert normalize_channel_name("Willow 2 HD") == "willow 2"
    assert normalize_channel_name("World Fishing Network HD (US)") == "world fishing network"


def test_normalize_keeps_distinguishing_digits():
    # ESPN vs ESPN2 must stay distinct after normalization
    assert normalize_channel_name("ESPN HD") != normalize_channel_name("ESPN2 HD")
    assert normalize_channel_name("ESPN2 HD") == "espn2"


def test_normalize_does_not_drop_identity_words():
    # "USA" is identity here, not a quality tag — must survive
    assert normalize_channel_name("USA Network HD") == "usa network"


# =========================================================== region prefixes (yke)


def test_normalize_strips_country_grouping_prefix():
    # Provider grouping label + delimiter is not identity — strip it so the
    # name matches the bare EPGData catalog name.
    assert normalize_channel_name("US: ESPN FHD") == "espn"
    assert normalize_channel_name("UK | Sky Sports Main Event") == "sky sports main event"
    assert normalize_channel_name("CA: TSN 1 HD") == "tsn 1"


def test_normalize_prefix_strip_preserves_identity_usa_network():
    # The delimiter is the safety anchor: "USA Network" has no delimiter so
    # "usa" survives; only the delimited grouping label "US: " is stripped.
    assert normalize_channel_name("USA Network HD") == "usa network"
    assert normalize_channel_name("US: USA Network") == "usa network"
    assert normalize_channel_name("US: USA Network West") == "usa network west"


def test_normalize_does_not_strip_undelimited_or_non_region_tokens():
    # No delimiter -> not a grouping prefix; an out-of-allowlist token is kept.
    assert normalize_channel_name("US Open Tennis") == "us open tennis"
    assert normalize_channel_name("ESPN: College Extra") == "espn college extra"


def test_prefix_strip_enables_name_resolution():
    # End-to-end: a prefixed stream now name-resolves to the bare catalog entry.
    streams = [{"id": 7, "name": "US: beIn Sports Xtra FHD", "tvg_id": "beINSportsXtra.us"}]
    epg = _epgdata([(100, "113143", "beIn Sports Xtra")])
    res, stats = resolve_program_tvg_ids(streams, epg, {})
    assert res == {"beINSportsXtra.us": "113143"}
    assert stats["name"] == 1


# ====================================================================== cascade


def test_direct_tvg_id_match_wins():
    streams = [{"id": 1, "name": "Whatever", "tvg_id": "82547"}]
    epg = _epgdata([(100, "82547", "FS1 HD")])
    res, stats = resolve_program_tvg_ids(streams, epg, {})
    assert res == {"82547": "82547"}
    assert stats["direct"] == 1


def test_channel_outranks_name():
    # Stream name would name-match "FS1 HD" (tvg 82547), but the curated channel
    # points at a different EPGData row — the channel must win.
    streams = [{"id": 7, "name": "FS1 HD", "tvg_id": "FoxSports1.us"}]
    epg = _epgdata([(100, "82547", "FS1 HD"), (200, "99999", "FS1 Regional")])
    stream_channels = {7: {"epg_data_id": 200}}
    res, stats = resolve_program_tvg_ids(streams, epg, stream_channels)
    assert res == {"FoxSports1.us": "99999"}
    assert stats["channel"] == 1
    assert stats["name"] == 0


def test_name_match_used_when_no_channel():
    streams = [{"id": 7, "name": "beIn Sports Xtra FHD", "tvg_id": "beINSportsXtra.us"}]
    epg = _epgdata([(100, "113143", "beIn Sports Xtra")])
    res, stats = resolve_program_tvg_ids(streams, epg, {})
    assert res == {"beINSportsXtra.us": "113143"}
    assert stats["name"] == 1


def test_ambiguous_name_is_skipped():
    # Two EPGData rows normalize to the same name but have different tvg_ids →
    # ambiguous → no resolution (don't guess).
    streams = [{"id": 7, "name": "Sky Sports HD", "tvg_id": "sky.us"}]
    epg = _epgdata([(1, "aaa", "Sky Sports"), (2, "bbb", "Sky Sports FHD")])
    res, stats = resolve_program_tvg_ids(streams, epg, {})
    assert res == {}
    assert stats["ambiguous_name"] == 1
    assert stats["unresolved"] == 1


def test_espn_does_not_resolve_to_espn2():
    streams = [{"id": 7, "name": "ESPN HD", "tvg_id": "espn.us"}]
    epg = _epgdata([(1, "espn2id", "ESPN2 HD")])
    res, _ = resolve_program_tvg_ids(streams, epg, {})
    assert res == {}


def test_effective_epg_data_id_preferred_over_base():
    streams = [{"id": 7, "name": "X", "tvg_id": "x.us"}]
    epg = _epgdata([(10, "base", "A"), (20, "override", "B")])
    stream_channels = {7: {"epg_data_id": 10, "effective_epg_data_id": 20}}
    res, _ = resolve_program_tvg_ids(streams, epg, stream_channels)
    assert res == {"x.us": "override"}


def test_channel_outranks_direct():
    # Curated channel mapping is priority 1 — even when the stream tvg_id would
    # also match directly, the channel-linked EPGData wins.
    streams = [{"id": 7, "name": "ESPN", "tvg_id": "82547"}]
    epg = _epgdata([(100, "82547", "FS1 HD"), (200, "99999", "ESPN HD")])
    stream_channels = {7: {"epg_data_id": 200}}
    res, stats = resolve_program_tvg_ids(streams, epg, stream_channels)
    assert res == {"82547": "99999"}  # channel-linked, not the direct id match
    assert stats["channel"] == 1 and stats["direct"] == 0


def test_active_source_filter_restricts_name_and_direct():
    # Only EPGData rows from active sources are eligible for direct/name.
    streams = [
        {"id": 1, "name": "beIn Sports Xtra", "tvg_id": "bein.us"},  # name match
        {"id": 2, "name": "x", "tvg_id": "55555"},  # direct match
    ]
    epg = [
        {"id": 100, "tvg_id": "113143", "name": "beIn Sports Xtra", "epg_source": 9},  # inactive
        {"id": 101, "tvg_id": "55555", "name": "Whatever", "epg_source": 9},  # inactive
    ]
    # source 9 inactive -> nothing resolves
    res, _ = resolve_program_tvg_ids(streams, epg, {}, active_source_ids={16, 17})
    assert res == {}
    # source 9 active -> both resolve (name + direct)
    res2, stats2 = resolve_program_tvg_ids(streams, epg, {}, active_source_ids={9})
    assert res2 == {"bein.us": "113143", "55555": "55555"}
    assert stats2["name"] == 1 and stats2["direct"] == 1


def test_channel_link_trusted_even_if_source_inactive():
    # Channel curation uses the full catalog, so an inactive-source link still
    # resolves (it just yields no programs downstream).
    streams = [{"id": 7, "name": "X", "tvg_id": "x.us"}]
    epg = [{"id": 200, "tvg_id": "77777", "name": "ESPN", "epg_source": 9}]
    res, stats = resolve_program_tvg_ids(
        streams, epg, {7: {"epg_data_id": 200}}, active_source_ids={16}
    )
    assert res == {"x.us": "77777"}
    assert stats["channel"] == 1


def test_unresolved_when_nothing_matches():
    streams = [{"id": 7, "name": "Totally Unknown Channel", "tvg_id": "unk.us"}]
    epg = _epgdata([(1, "82547", "FS1 HD")])
    res, stats = resolve_program_tvg_ids(streams, epg, {})
    assert res == {}
    assert stats["unresolved"] == 1


def test_streams_without_tvg_id_are_ignored():
    streams = [{"id": 7, "name": "FS1 HD", "tvg_id": ""}]
    epg = _epgdata([(100, "82547", "FS1 HD")])
    res, _ = resolve_program_tvg_ids(streams, epg, {})
    assert res == {}


def test_first_stream_wins_for_shared_tvg_id():
    streams = [
        {"id": 1, "name": "FS1 HD", "tvg_id": "dup.us"},
        {"id": 2, "name": "Other", "tvg_id": "dup.us"},
    ]
    epg = _epgdata([(100, "82547", "FS1 HD")])
    res, _ = resolve_program_tvg_ids(streams, epg, {})
    assert res == {"dup.us": "82547"}
