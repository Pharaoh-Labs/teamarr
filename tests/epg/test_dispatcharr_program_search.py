"""Tests for EPGManager.search_programs() + program-search feature detection.

Covers the client surface added in teamarr-183.2:
- DispatcharrProgram.from_api parsing (embedded streams/channels, datetimes)
- supports_program_search() caching + 404 graceful degradation
- search_programs() param building, pagination, and unsupported short-circuit

The broader matching/lifecycle test matrix lives in teamarr-183.7.
"""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import httpx
import pytest

from teamarr.consumers.matching.epg_index import EPGProgramIndex
from teamarr.dispatcharr.client import DispatcharrClient
from teamarr.dispatcharr.managers.epg import EPGManager
from teamarr.dispatcharr.types import DispatcharrProgram

# =============================================================================
# DispatcharrProgram.from_api
# =============================================================================

SAMPLE_PROGRAM = {
    "id": 20292567,
    "title": "Alabama at Auburn",
    "sub_title": "Iron Bowl",
    "description": "College football rivalry.",
    "start_time": "2026-06-01T18:00:00Z",
    "end_time": "2026-06-01T21:00:00Z",
    "tvg_id": "60048",
    "epg_source": "^EPG USA - Jesmann 14-day",
    "epg_name": "ESPN",
    "epg_icon_url": "https://example/espn.png",
    "channels": [{"id": 50, "name": "ESPN HD", "tvg_id": "60048"}],
    "streams": [{"id": 919239, "name": "ESPN FHD", "tvg_id": "60048", "m3u_account": "X"}],
}


def test_program_from_api_full():
    p = DispatcharrProgram.from_api(SAMPLE_PROGRAM)
    assert p.id == 20292567
    assert p.title == "Alabama at Auburn"
    assert p.sub_title == "Iron Bowl"
    assert p.tvg_id == "60048"
    assert p.stream_ids == (919239,)
    assert p.channel_ids == (50,)
    assert p.is_teamarr is False


def test_program_datetime_parsing():
    p = DispatcharrProgram.from_api(SAMPLE_PROGRAM)
    assert p.start_dt is not None and p.end_dt is not None
    assert p.start_dt.isoformat() == "2026-06-01T18:00:00+00:00"
    assert p.end_dt.isoformat() == "2026-06-01T21:00:00+00:00"


def test_program_handles_missing_optional_fields():
    p = DispatcharrProgram.from_api({"id": 1, "tvg_id": "x", "title": "T"})
    assert p.stream_ids == ()
    assert p.channel_ids == ()
    assert p.start_dt is None
    assert p.end_dt is None


def test_program_is_teamarr_flag():
    p = DispatcharrProgram.from_api({**SAMPLE_PROGRAM, "epg_source": "_Teamarr"})
    assert p.is_teamarr is True


# =============================================================================
# Feature detection
# =============================================================================


def _mgr(status: int):
    """Build a mock httpx-style response with a given status code."""
    resp = MagicMock()
    resp.status_code = status
    return resp


def test_supports_program_search_true_and_caches():
    client = MagicMock()
    client.get.return_value = _mgr(200)
    mgr = EPGManager(client)

    assert mgr.supports_program_search() is True
    # cached — second call does not re-probe
    assert mgr.supports_program_search() is True
    assert client.get.call_count == 1


def test_supports_program_search_404_disables_and_caches():
    client = MagicMock()
    client.get.return_value = _mgr(404)
    mgr = EPGManager(client)

    assert mgr.supports_program_search() is False
    assert mgr.supports_program_search() is False
    assert client.get.call_count == 1


def test_supports_program_search_transient_not_cached():
    client = MagicMock()
    client.get.return_value = _mgr(500)
    mgr = EPGManager(client)

    assert mgr.supports_program_search() is False
    # 500 is not cached — a later call re-probes
    assert mgr.supports_program_search() is False
    assert client.get.call_count == 2


def test_supports_program_search_no_response_not_cached():
    client = MagicMock()
    client.get.return_value = None
    mgr = EPGManager(client)

    assert mgr.supports_program_search() is False
    assert mgr._programs_search_supported is None


# =============================================================================
# search_programs
# =============================================================================


def test_search_programs_unsupported_short_circuits():
    client = MagicMock()
    client.get.return_value = _mgr(404)
    mgr = EPGManager(client)

    assert mgr.search_programs(tvg_id="60048") == []
    # never reaches pagination
    client.paginated_get_or_none.assert_not_called()


def test_search_programs_builds_params_and_maps_results():
    client = MagicMock()
    client.get.return_value = _mgr(200)
    client.paginated_get_or_none.return_value = [SAMPLE_PROGRAM]
    mgr = EPGManager(client)

    progs = mgr.search_programs(
        tvg_id="60048",
        start_before="2026-06-02T00:00:00Z",
        end_after="2026-06-01T00:00:00Z",
        title="Alabama at Auburn",
        page_size=500,
    )

    assert len(progs) == 1
    assert progs[0].title == "Alabama at Auburn"

    endpoint = client.paginated_get_or_none.call_args.args[0]
    assert client.paginated_get_or_none.call_args.kwargs["require_complete"] is True
    assert endpoint.startswith("/api/epg/programs/search/?")
    assert "tvg_id=60048" in endpoint
    assert "page_size=500" in endpoint
    # urlencode escapes spaces in the title filter
    assert "title=Alabama+at+Auburn" in endpoint
    assert "start_before=2026-06-02" in endpoint


def test_search_programs_skips_malformed_records():
    client = MagicMock()
    client.get.return_value = _mgr(200)
    client.paginated_get_or_none.return_value = [SAMPLE_PROGRAM, {"no_id": True}]
    mgr = EPGManager(client)

    progs = mgr.search_programs(tvg_id="60048")
    assert len(progs) == 1


def test_search_programs_reports_failed_read_as_none():
    client = MagicMock()
    client.get.return_value = _mgr(200)
    client.paginated_get_or_none.return_value = None
    assert EPGManager(client).search_programs(tvg_id="60048") is None


def test_search_programs_retries_after_a_transient_probe_failure():
    client = MagicMock()
    client.get.side_effect = [_mgr(503), _mgr(200)]
    client.paginated_get_or_none.return_value = [SAMPLE_PROGRAM]
    mgr = EPGManager(client)

    assert mgr.search_programs(tvg_id="60048") is None
    programs = mgr.search_programs(tvg_id="60048")
    assert programs is not None and [p.id for p in programs] == [SAMPLE_PROGRAM["id"]]


@pytest.mark.parametrize("failure", ["first-page", "later-page", "invalid-json"])
def test_index_retries_incomplete_search_for_the_next_group(monkeypatch, failure):
    client = DispatcharrClient.__new__(DispatcharrClient)
    follow_url = "/api/epg/programs/search/?page=2&page_size=500&tvg_id=60048"
    recovered = False

    def get(path):
        if path.endswith("?page_size=1"):
            return httpx.Response(200)
        if path == follow_url:
            return httpx.Response(503)
        if recovered:
            return httpx.Response(200, json={"results": [SAMPLE_PROGRAM]})
        if failure == "later-page":
            return httpx.Response(200, json={"results": [SAMPLE_PROGRAM], "next": follow_url})
        if failure == "invalid-json":
            return httpx.Response(200, text="bad gateway")
        return httpx.Response(503)

    monkeypatch.setattr(client, "get", get)
    manager = EPGManager(client)
    cache = {}
    start, end = datetime(2026, 6, 1, tzinfo=UTC), datetime(2026, 6, 2, tzinfo=UTC)

    first = EPGProgramIndex.build(manager, {"stream-A": "60048"}, start, end, program_cache=cache)
    assert not first
    assert not cache
    recovered = True
    index = EPGProgramIndex.build(manager, {"stream-B": "60048"}, start, end, program_cache=cache)
    assert index.tvg_ids() == ["stream-B"]
    assert index.program_count() == 1
