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


# ============================================= region prefixes: item 10 (Phase 3a)


def test_normalize_strips_spaced_dash_delimiter():
    # New delimiter: a spaced dash is as valid a grouping separator as ":" or
    # "|". Today _REGION_PREFIX only recognizes [:|], so "US - ESPN" is left
    # as "us espn" instead of being stripped to "espn".
    assert normalize_channel_name("US - ESPN") == "espn"


def test_normalize_allowlist_extended_with_asia_pacific_and_middle_east_codes():
    # New allowlist codes: jp, kr, cn, za, sa, qa, ae, il, pk, ph, th, vn, my,
    # sg, id, hk, tw. None of these are in the current _REGION_PREFIX
    # allowlist, so all of these currently stay unstripped (e.g. "jp nhk").
    assert normalize_channel_name("JP: NHK") == "nhk"
    assert normalize_channel_name("KR: KBS") == "kbs"
    assert normalize_channel_name("CN: CCTV") == "cctv"
    assert normalize_channel_name("ZA: SuperSport") == "supersport"
    assert normalize_channel_name("SA: Al Jazeera") == "al jazeera"
    assert normalize_channel_name("QA: BeIN") == "bein"
    assert normalize_channel_name("AE: Dubai Sports") == "dubai sports"
    assert normalize_channel_name("IL: Sport1") == "sport1"
    assert normalize_channel_name("PK: PTV") == "ptv"
    assert normalize_channel_name("PH: ABS-CBN") == "abs cbn"
    assert normalize_channel_name("TH: Thai PBS") == "thai pbs"
    assert normalize_channel_name("VN: VTV") == "vtv"
    assert normalize_channel_name("MY: Astro") == "astro"
    assert normalize_channel_name("SG: StarHub") == "starhub"
    assert normalize_channel_name("ID: RCTI") == "rcti"
    assert normalize_channel_name("HK: TVB") == "tvb"
    assert normalize_channel_name("TW: CTV") == "ctv"


def test_normalize_new_allowlist_code_with_spaced_dash():
    # The two new-contract pieces (spaced dash + expanded allowlist) combined.
    assert normalize_channel_name("JP - NHK World") == "nhk world"


def test_normalize_no_delimiter_still_not_stripped():
    # NON-goal: "USA ESPN" has no delimiter at all (no ":", "|", or " - "),
    # so it stays ambiguous and must NOT be treated as a grouping prefix, same
    # as today. Guards against an implementation that starts matching on bare
    # whitespace once dash-support is added.
    assert normalize_channel_name("USA ESPN") == "usa espn"


def test_normalize_city_code_false_positive_guard():
    # NON-goal: "LA" (Los Angeles) is deliberately NOT in the allowlist even
    # though the new dash delimiter would otherwise make "LA - Lakers Live"
    # look like a region-prefixed name. Adding the dash delimiter must not
    # accidentally treat city abbreviations as country codes.
    assert normalize_channel_name("LA - Lakers Live") == "la lakers live"


def test_normalize_unspaced_dash_not_treated_as_delimiter():
    # NON-goal: only a SPACED dash (" - ") is a delimiter. An unspaced dash
    # ("FR-ESPN") must stay untouched by the region-prefix step so real names
    # like "Bein-Sports" are never accidentally split on their hyphen.
    assert normalize_channel_name("FR-ESPN") == "fr espn"


# ============================================ network aliases: item 11 (Phase 3a)


def test_fs1_and_fox_sports_1_normalize_to_the_same_string():
    # NETWORK_ALIASES doesn't exist yet -- "fs1" and "fox sports 1" are
    # currently two distinct normalized strings.
    assert normalize_channel_name("FS1 HD") == normalize_channel_name("Fox Sports 1 FHD")
    assert normalize_channel_name("FS1 HD") == "fox sports 1"


def test_region_prefixed_fs1_also_aliases():
    # Alias resolution runs AFTER region-prefix stripping.
    assert normalize_channel_name("US: FS1") == "fox sports 1"


def test_fs2_aliases_to_fox_sports_2():
    assert normalize_channel_name("FS2") == "fox sports 2"


def test_nbcsn_aliases_to_nbc_sports_network():
    assert normalize_channel_name("NBCSN") == "nbc sports network"


def test_cbssn_aliases_to_cbs_sports_network():
    assert normalize_channel_name("CBSSN") == "cbs sports network"


def test_espn2_does_not_collapse_to_espn():
    # Pinned NON-goal: ESPN2 is a distinct channel, not an "ESPN" abbreviation.
    assert normalize_channel_name("ESPN2 HD") == "espn2"
    assert normalize_channel_name("ESPN2 HD") != normalize_channel_name("ESPN HD")


def test_sn_aliases_to_sportsnet_only_as_whole_name():
    assert normalize_channel_name("SN 360") == "sportsnet 360"


def test_sn_substring_inside_word_is_untouched():
    # Pinned NON-goal: "sn" must only alias when it IS the whole normalized
    # name (or a whole leading token per "sn 360"), not when it's merely
    # contained inside another word.
    assert normalize_channel_name("Wisconsin Sports") == "wisconsin sports"


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


# ==================================================================== loopback


_UUID = "523949c3-ac85-4c4a-baa7-bc9800000000"


def _loopback_stream(sid=7, tvg="166", name="Sky Sports F1 HD", uuid=_UUID):
    # A Dispatcharr-loopback M3U stream: tvg_id is the channel NUMBER (churns
    # meaning), url names the source channel by its stable uuid.
    return {
        "id": sid,
        "name": name,
        "tvg_id": tvg,
        "url": f"http://192.168.7.220:9191/proxy/ts/stream/{uuid}",
    }


def test_loopback_resolves_via_source_channel_uuid():
    # Live case: the loopback stream is in NO channel, its tvg_id ("166", a
    # channel number) exists in no guide, and its name is ambiguous across
    # multiple guide entries — only the proxy URL identifies it.
    streams = [_loopback_stream()]
    epg = _epgdata([
        (200, "87578", "Sky Sports F1 HD"),
        (201, "131261", "Sky Sports F1 UHD"),
    ])
    res, stats = resolve_program_tvg_ids(
        streams, epg, {}, channel_by_uuid={_UUID: {"epg_data_id": 200}}
    )
    assert res == {"166": "87578"}
    assert stats["loopback"] == 1


def test_loopback_survives_stream_id_churn():
    # The loopback account recreates streams (new ids) on every refresh; the
    # uuid in the URL is the stable identity, so resolution must not depend
    # on the stream id appearing in the stream->channel map.
    streams = [_loopback_stream(sid=999999)]
    epg = _epgdata([(200, "87578", "Sky Sports F1 HD")])
    res, stats = resolve_program_tvg_ids(
        streams, epg, {12345: {"epg_data_id": 200}},  # stale map, old id
        channel_by_uuid={_UUID: {"epg_data_id": 200}},
    )
    assert res == {"166": "87578"}
    assert stats["loopback"] == 1


def test_channel_membership_outranks_loopback():
    streams = [_loopback_stream(sid=7)]
    epg = _epgdata([(200, "87578", "Sky Sports F1 HD"), (300, "99999", "Other")])
    res, stats = resolve_program_tvg_ids(
        streams, epg, {7: {"epg_data_id": 300}},
        channel_by_uuid={_UUID: {"epg_data_id": 200}},
    )
    assert res == {"166": "99999"}
    assert stats["channel"] == 1 and stats["loopback"] == 0


def test_loopback_uuid_lookup_is_case_insensitive():
    streams = [_loopback_stream(uuid=_UUID.upper())]
    epg = _epgdata([(200, "87578", "Sky Sports F1 HD")])
    res, stats = resolve_program_tvg_ids(
        streams, epg, {}, channel_by_uuid={_UUID: {"epg_data_id": 200}}
    )
    assert res == {"166": "87578"}
    assert stats["loopback"] == 1


def test_unknown_uuid_falls_through_to_name_cascade():
    # A proxy-shaped URL whose uuid isn't a known channel must not block the
    # rest of the cascade.
    streams = [_loopback_stream(uuid="00000000-0000-0000-0000-000000000000")]
    epg = _epgdata([(200, "87578", "Sky Sports F1 HD")])
    res, stats = resolve_program_tvg_ids(
        streams, epg, {}, channel_by_uuid={_UUID: {"epg_data_id": 200}}
    )
    assert res == {"166": "87578"}
    assert stats["name"] == 1


def test_non_loopback_url_ignores_uuid_map():
    streams = [{
        "id": 7, "name": "Sky Sports F1 HD", "tvg_id": "sky.uk",
        "url": "https://provider.example/live/user/pass/369549.ts",
    }]
    epg = _epgdata([(200, "87578", "Sky Sports F1 HD")])
    res, stats = resolve_program_tvg_ids(
        streams, epg, {}, channel_by_uuid={_UUID: {"epg_data_id": 200}}
    )
    assert res == {"sky.uk": "87578"}
    assert stats["name"] == 1 and stats["loopback"] == 0


# ===================================================== generated-guide poisoning


def test_own_guide_channel_link_falls_through_to_loopback():
    # Feedback loop (live, Belgian GP): a matched stream gets consolidated
    # into the managed event channel it matched; next run the channel path
    # resolves it to our OWN generated guide, whose programmes the index
    # excludes — EPG matching dies for that stream forever. Own-guide links
    # must not terminate the cascade.
    streams = [_loopback_stream(sid=7)]
    epg = _epgdata([(200, "87578", "Sky Sports F1 HD")])
    epg.append({"id": 900, "tvg_id": "teamarr-f1-race", "name": "F1: Belgian GP - Race",
                "epg_source": 32})
    res, stats = resolve_program_tvg_ids(
        streams, epg,
        {7: {"epg_data_id": 900}},          # membership in own event channel
        channel_by_uuid={_UUID: {"epg_data_id": 200}},
        own_source_id=32,
    )
    assert res == {"166": "87578"}
    assert stats["loopback"] == 1 and stats["channel"] == 0


def test_own_guide_link_still_trusted_when_own_source_unknown():
    # Without own_source_id (back-compat), behavior is unchanged for
    # non-synthetic tvg ids.
    streams = [_loopback_stream(sid=7)]
    epg = _epgdata([(200, "87578", "Sky Sports F1 HD")])
    epg.append({"id": 900, "tvg_id": "teamarr-f1-race", "name": "F1: Belgian GP - Race",
                "epg_source": 32})
    res, stats = resolve_program_tvg_ids(
        streams, epg, {7: {"epg_data_id": 900}},
        channel_by_uuid={_UUID: {"epg_data_id": 200}},
    )
    assert res == {"166": "teamarr-f1-race"}
    assert stats["channel"] == 1


def test_sibling_event_guide_link_falls_through():
    # Same poisoning via a sibling install writing to the same Dispatcharr:
    # its event channels' synthetic guide airs all-day "Coming up: F1
    # Racing ..." placeholder blocks that bind the stream to every session
    # (live: TSN 5 landed on all five Belgian GP session channels). Synthetic
    # event guides are identified by tvg prefix, regardless of source id.
    streams = [_loopback_stream(sid=7)]
    epg = _epgdata([(200, "87578", "Sky Sports F1 HD")])
    epg.append({"id": 950, "tvg_id": "apex-event-600057439-qualifying",
                "name": "F1 | Belgian Grand Prix - Qualifying", "epg_source": 8})
    res, stats = resolve_program_tvg_ids(
        streams, epg,
        {7: {"epg_data_id": 950}},          # membership in sibling's channel
        channel_by_uuid={_UUID: {"epg_data_id": 200}},
        own_source_id=32,
    )
    assert res == {"166": "87578"}
    assert stats["loopback"] == 1 and stats["channel"] == 0


def test_own_event_guide_prefix_blocked_even_without_source_id():
    # Our own event-channel tvg prefix is synthetic by construction — blocked
    # by prefix even when the own source id could not be resolved.
    streams = [_loopback_stream(sid=7)]
    epg = _epgdata([(200, "87578", "Sky Sports F1 HD")])
    epg.append({"id": 960, "tvg_id": "teamarr-event-600057439-race",
                "name": "F1 | Belgian Grand Prix - Race", "epg_source": 32})
    res, stats = resolve_program_tvg_ids(
        streams, epg, {7: {"epg_data_id": 960}},
        channel_by_uuid={_UUID: {"epg_data_id": 200}},
    )
    assert res == {"166": "87578"}
    assert stats["loopback"] == 1 and stats["channel"] == 0
