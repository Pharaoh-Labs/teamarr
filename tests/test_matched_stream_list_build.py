"""Regression: matched stream list must not collapse duplicate titles."""

from unittest.mock import MagicMock, patch

from teamarr.consumers.event_group_processor import EventGroupProcessor
from teamarr.consumers.matching.matcher import BatchMatchResult, MatchedStreamResult


def test_build_matched_stream_list_same_title_distinct_stream_ids():
    """Identical stream names on different M3U lines map to separate stream dicts."""
    proc = EventGroupProcessor(db_factory=MagicMock())
    event = MagicMock()
    event.id = "evt-soccer-1"
    event.sport = "soccer"
    event.league = "epl"

    streams = [
        {"id": 101, "name": "AU (STAN 03) | Crystal Palace v Newcastle"},
        {"id": 102, "name": "AU (STAN 03) | Crystal Palace v Newcastle"},
    ]
    title = streams[0]["name"]
    results = [
        MatchedStreamResult(
            stream_name=title,
            stream_id=101,
            matched=True,
            included=True,
            event=event,
        ),
        MatchedStreamResult(
            stream_name=title,
            stream_id=102,
            matched=True,
            included=True,
            event=event,
        ),
    ]
    batch = BatchMatchResult(results=results)

    with patch.object(
        EventGroupProcessor,
        "_load_sport_durations_cached",
        return_value={},
    ):
        matched = proc._build_matched_stream_list(streams, batch)

    assert len(matched) == 2
    assert {m["stream"]["id"] for m in matched} == {101, 102}
