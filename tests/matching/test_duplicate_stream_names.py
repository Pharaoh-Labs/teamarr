"""Identically named streams must each survive matched-stream list building.

Regression for GitHub issue #264: users with multiple M3U accounts from the
same provider get identically NAMED streams with distinct stream IDs. The
matched-stream list builder keyed its stream lookup by name, collapsing all
duplicates onto one stream dict — so only one account's stream was ever
attached to the consolidated channel. Lookup must be ID-first.
"""

from types import SimpleNamespace

from teamarr.consumers.matching.matcher import BatchMatchResult, MatchedStreamResult
from tests.fakes import make_bare_processor


def _make_processor():
    # Segment expansion needs DB-backed sport durations — pass entries through.
    return make_bare_processor(
        _expand_ufc_segments=lambda matched, tz=None: matched,
        _expand_racing_segments=lambda matched: matched,
    )


def _result(stream_id: int, stream_name: str, event) -> MatchedStreamResult:
    return MatchedStreamResult(
        stream_name=stream_name,
        stream_id=stream_id,
        matched=True,
        included=True,
        event=event,
    )


def test_identically_named_streams_each_produce_matched_entry():
    event = SimpleNamespace(id="401234", name="Yankees vs Red Sox")
    # Same provider via two M3U logins: same name, different stream IDs.
    streams = [
        {"id": 101, "name": "MLB: Yankees vs Red Sox", "m3u_account_id": 1},
        {"id": 202, "name": "MLB: Yankees vs Red Sox", "m3u_account_id": 2},
    ]
    match_result = BatchMatchResult(
        results=[
            _result(101, "MLB: Yankees vs Red Sox", event),
            _result(202, "MLB: Yankees vs Red Sox", event),
        ]
    )

    proc = _make_processor()
    matched = proc._build_matched_stream_list(streams, match_result)

    attached_ids = {m["stream"]["id"] for m in matched}
    assert attached_ids == {101, 202}
    # Each entry carries its own account's stream dict, not a shared one.
    accounts = {m["stream"]["m3u_account_id"] for m in matched}
    assert accounts == {1, 2}


def test_name_fallback_still_works_without_stream_id():
    event = SimpleNamespace(id="401234", name="Yankees vs Red Sox")
    streams = [{"name": "MLB: Yankees vs Red Sox"}]  # no id key
    match_result = BatchMatchResult(
        results=[_result(0, "MLB: Yankees vs Red Sox", event)]
    )

    proc = _make_processor()
    matched = proc._build_matched_stream_list(streams, match_result)

    assert len(matched) == 1
    assert matched[0]["stream"]["name"] == "MLB: Yankees vs Red Sox"
