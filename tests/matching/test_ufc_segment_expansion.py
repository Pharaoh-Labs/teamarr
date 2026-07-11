"""UFC segment expansion must preserve matcher metadata (#344).

expand_ufc_segments rebuilds each matched dict into per-segment entries; it
used to construct the new dicts from scratch, silently dropping match_method,
match_type, feed fields, and the EPG program window. EPG-matched streams then
persisted match_method=NULL and were ordered as plain event streams with
full-life membership.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from teamarr.consumers.ufc_segments import expand_ufc_segments


@dataclass
class FakeUFCEvent:
    """Minimal UFC Event stand-in with the segment-timing fields."""

    id: str = "ufc-329"
    name: str = "UFC 329: A vs B"
    sport: str = "mma"
    league: str = "ufc"
    start_time: datetime = field(
        default_factory=lambda: datetime(2026, 7, 11, 22, 0, tzinfo=UTC)
    )
    segment_times: dict | None = None
    main_card_start: datetime | None = None


def _matched(stream_name: str, event, **extra) -> dict:
    """A matched-stream dict as _build_matched_stream_list produces it."""
    entry = {
        "stream": {"id": 1, "name": stream_name},
        "event": event,
        "card_segment": None,
        "feed_hint": None,
        "match_type": "event",
        "match_method": None,
        "epg_program_start": None,
        "epg_program_end": None,
    }
    entry.update(extra)
    return entry


def test_ufc_expansion_preserves_matcher_metadata():
    event = FakeUFCEvent()
    prog_start = datetime(2026, 7, 11, 22, 0, tzinfo=UTC)
    prog_end = prog_start + timedelta(hours=3)

    matched = [
        _matched(
            "TNT Sports 1 HD",
            event,
            match_method="epg",
            epg_program_start=prog_start,
            epg_program_end=prog_end,
        )
    ]

    expanded = expand_ufc_segments(matched)

    assert expanded, "UFC stream should expand into at least one segment entry"
    for entry in expanded:
        assert entry["match_method"] == "epg"
        assert entry["match_type"] == "event"
        assert entry["epg_program_start"] == prog_start
        assert entry["epg_program_end"] == prog_end
        assert entry["segment"]  # segment fields still populated
        assert entry["segment_start"] is not None


def test_ufc_expansion_segment_fields_override_spread():
    """Spreading the original match must not clobber the per-segment fields."""
    event = FakeUFCEvent(
        segment_times={
            "prelims": datetime(2026, 7, 11, 20, 0, tzinfo=UTC),
            "main_card": datetime(2026, 7, 11, 22, 0, tzinfo=UTC),
        }
    )
    matched = [
        _matched("UFC 329 Prelims", event, card_segment="prelims", match_method="epg"),
        _matched("UFC 329 Main Card", event, card_segment="main_card", match_method="epg"),
    ]

    expanded = expand_ufc_segments(matched)

    segments = {e["segment"] for e in expanded}
    assert segments == {"prelims", "main_card"}
    by_segment = {e["segment"]: e for e in expanded}
    assert by_segment["prelims"]["segment_start"] == event.segment_times["prelims"]
    assert by_segment["main_card"]["segment_start"] == event.segment_times["main_card"]
    assert all(e["match_method"] == "epg" for e in expanded)


def test_non_ufc_stream_passes_through_untouched():
    from tests.fakes import make_event

    event = make_event(sport="soccer", league="fifa.world")
    matched = [_matched("TNT Sports 2", event, match_method="epg")]

    expanded = expand_ufc_segments(matched)

    assert len(expanded) == 1
    assert expanded[0]["match_method"] == "epg"
    assert "segment_start" not in expanded[0]
