"""Tests for EPGProgramIndex — scoped fetch + tvg_id index + overlap lookup.

Covers teamarrv2-183.3:
- fetch is scoped to the distinct candidate tvg_ids (one call per tvg_id)
- _Teamarr programs are excluded
- unsupported endpoint / empty tvg_id set short-circuit cleanly
- overlap lookup returns only programs intersecting the event window
- programs with unparseable times are never returned by lookup
"""

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock

from teamarr.consumers.matching.epg_index import EPGProgramIndex
from teamarr.dispatcharr.types import DispatcharrProgram


def _prog(pid, tvg, start, end, title="MLB Baseball", source="ext", **kw):
    """Build a DispatcharrProgram with ISO-Z times from datetimes."""
    return DispatcharrProgram.from_api(
        {
            "id": pid,
            "tvg_id": tvg,
            "title": title,
            "start_time": start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if start else None,
            "end_time": end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if end else None,
            "epg_source": source,
            **kw,
        }
    )


def _epg_mgr(supported=True):
    mgr = MagicMock()
    mgr.supports_program_search.return_value = supported
    return mgr


# ============================================================== build / scope


def test_build_fetches_by_resolved_tvg_and_keys_by_stream_tvg():
    mgr = _epg_mgr()
    base = datetime(2026, 6, 1, 18, tzinfo=UTC)
    mgr.search_programs.side_effect = lambda tvg_id, **kw: [
        _prog(1, tvg_id, base, base + timedelta(hours=3))
    ]

    # stream tvg_id -> resolved EPG-source tvg_id: fetched by resolved id,
    # indexed by the stream tvg_id.
    idx = EPGProgramIndex.build(
        mgr,
        tvg_id_resolution={"FoxSports1.us": "82547", "ESPN.us": "12345"},
        window_start=base,
        window_end=base + timedelta(days=1),
    )

    # one call per resolved id, querying by the RESOLVED tvg_id (not stream's)
    assert mgr.search_programs.call_count == 2
    called = {c.kwargs["tvg_id"] for c in mgr.search_programs.call_args_list}
    assert called == {"82547", "12345"}
    assert idx.program_count() == 2
    # keyed by the stream tvg_id so the matcher can look it up
    assert set(idx.tvg_ids()) == {"FoxSports1.us", "ESPN.us"}


def test_build_excludes_teamarr_programs():
    mgr = _epg_mgr()
    base = datetime(2026, 6, 1, 18, tzinfo=UTC)
    mgr.search_programs.return_value = [
        _prog(1, "espn", base, base + timedelta(hours=2), source="ext"),
        _prog(2, "espn", base, base + timedelta(hours=2), source="_Teamarr"),
    ]

    idx = EPGProgramIndex.build(mgr, {"espn": "espn"}, base, base + timedelta(days=1))
    assert idx.program_count() == 1
    assert idx.lookup("espn", base, base + timedelta(hours=1))[0].id == 1


def test_build_unsupported_endpoint_returns_empty():
    mgr = _epg_mgr(supported=False)
    base = datetime(2026, 6, 1, tzinfo=UTC)
    idx = EPGProgramIndex.build(mgr, {"espn": "espn"}, base, base + timedelta(days=1))
    assert not idx
    mgr.search_programs.assert_not_called()


def test_build_no_resolution_returns_empty_without_probe():
    mgr = _epg_mgr()
    base = datetime(2026, 6, 1, tzinfo=UTC)
    idx = EPGProgramIndex.build(mgr, {}, base, base + timedelta(days=1))
    assert not idx
    mgr.supports_program_search.assert_not_called()
    mgr.search_programs.assert_not_called()


def test_build_formats_window_as_utc_iso_z():
    mgr = _epg_mgr()
    mgr.search_programs.return_value = []
    # naive-ish aware window in a non-UTC tz to confirm conversion
    est = timezone(timedelta(hours=-5))
    start = datetime(2026, 6, 1, 19, tzinfo=est)  # 00:00Z next day
    EPGProgramIndex.build(mgr, {"espn": "espn"}, start, start + timedelta(hours=3))
    kw = mgr.search_programs.call_args.kwargs
    assert kw["end_after"] == "2026-06-02T00:00:00Z"
    assert kw["start_before"] == "2026-06-02T03:00:00Z"


# ===================================================================== lookup


def test_lookup_returns_only_overlapping_programs():
    mgr = _epg_mgr()
    base = datetime(2026, 6, 1, 0, tzinfo=UTC)
    mgr.search_programs.return_value = [
        _prog(1, "espn", base + timedelta(hours=1), base + timedelta(hours=3)),   # 01-03
        _prog(2, "espn", base + timedelta(hours=4), base + timedelta(hours=6)),   # 04-06
        _prog(3, "espn", base + timedelta(hours=8), base + timedelta(hours=11)),  # 08-11
    ]
    idx = EPGProgramIndex.build(mgr, {"espn": "espn"}, base, base + timedelta(days=1))

    # event 02:00-05:00 overlaps programs 1 and 2, not 3
    hits = idx.lookup("espn", base + timedelta(hours=2), base + timedelta(hours=5))
    assert [p.id for p in hits] == [1, 2]


def test_lookup_boundary_is_half_open():
    mgr = _epg_mgr()
    base = datetime(2026, 6, 1, 0, tzinfo=UTC)
    mgr.search_programs.return_value = [
        _prog(1, "espn", base, base + timedelta(hours=2)),  # 00-02
    ]
    idx = EPGProgramIndex.build(mgr, {"espn": "espn"}, base, base + timedelta(days=1))

    # event starting exactly at program end → no overlap
    assert idx.lookup("espn", base + timedelta(hours=2), base + timedelta(hours=4)) == []
    # event ending exactly at program start → no overlap
    assert idx.lookup("espn", base - timedelta(hours=2), base) == []
    # touching by 1 minute → overlap
    overlap = idx.lookup("espn", base + timedelta(hours=1, minutes=59), base + timedelta(hours=4))
    assert len(overlap) == 1


def test_lookup_skips_programs_without_times():
    mgr = _epg_mgr()
    base = datetime(2026, 6, 1, 0, tzinfo=UTC)
    mgr.search_programs.return_value = [
        _prog(1, "espn", None, None),  # unparseable window
        _prog(2, "espn", base, base + timedelta(hours=3)),
    ]
    idx = EPGProgramIndex.build(mgr, {"espn": "espn"}, base, base + timedelta(days=1))
    # both indexed, but only the timed one is windowable
    assert idx.program_count() == 2
    hits = idx.lookup("espn", base, base + timedelta(hours=1))
    assert [p.id for p in hits] == [2]


def test_lookup_unknown_tvg_id_returns_empty():
    idx = EPGProgramIndex({})
    base = datetime(2026, 6, 1, tzinfo=UTC)
    assert idx.lookup("nope", base, base + timedelta(hours=1)) == []


def test_categories_parsed_from_custom_properties():
    p = _prog(
        1, "espn", datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 1, 3, tzinfo=UTC),
        custom_properties={"categories": ["Sports", "Sports event", "Baseball"]},
    )
    assert p.categories == ("Sports", "Sports event", "Baseball")


# ===================================================================== merge (crs)


def test_merge_fills_gaps_and_keeps_existing():
    base = datetime(2026, 6, 3, 20, tzinfo=UTC)
    # Primary (DP) index already has tvg "A".
    idx = EPGProgramIndex({"A": [_prog(1, "A", base, base + timedelta(hours=2), source="dp")]})
    # Secondary (Xtream) source: a NEW tvg "B" plus a clashing "A".
    secondary = {
        "B": [_prog(-1, "B", base, base + timedelta(hours=2), source="_xtream")],
        "A": [_prog(-2, "A", base, base + timedelta(hours=2), source="_xtream")],
    }
    added = idx.merge(secondary)
    assert added == 1  # only B added; A is kept from the primary guide
    assert set(idx.tvg_ids()) == {"A", "B"}
    # A still the DP program (primary wins), B is the xtream one
    assert idx.programs_for("A")[0].epg_source == "dp"
    assert idx.programs_for("B")[0].epg_source == "_xtream"


def test_merge_skips_empty_and_blank():
    idx = EPGProgramIndex({})
    assert idx.merge({"A": [], "": [object()], None: [object()]}) == 0
    assert idx.tvg_ids() == []
