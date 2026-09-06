"""Test that stream matcher and preview expose extracted classification metadata."""

from datetime import date
from unittest.mock import MagicMock

from teamarr.consumers.event_group_processor.persistence import failure_reason_code
from teamarr.consumers.event_group_processor.results import PreviewStream
from teamarr.consumers.matching.matcher import MatchedStreamResult, StreamMatcher
from teamarr.consumers.matching.result import FailedReason, FilteredReason


def test_preview_stream_carries_and_serializes_extracted_metadata():
    ps = PreviewStream(
        stream_id=1,
        stream_name="US - NCAAF 17 : KENTUCKY CHRISTIAN @ MOREHEAD STATE - SEP 3 - 6:00 PM ET",
        matched=False,
        exclusion_reason="no_event_found",
        parsed_team1="US - NCAAF 17 : KENTUCKY CHRISTIAN",
        parsed_team2="MOREHEAD STATE",
        detected_league="college-football",
        extracted_date="2026-09-03",
        extracted_time="18:00:00",
        extracted_tz="America/New_York",
    )
    d = ps.to_dict()
    assert d["parsed_team1"] == "US - NCAAF 17 : KENTUCKY CHRISTIAN"
    assert d["parsed_team2"] == "MOREHEAD STATE"
    assert d["detected_league"] == "college-football"
    assert d["extracted_date"] == "2026-09-03"
    assert d["extracted_time"] == "18:00:00"
    assert d["extracted_tz"] == "America/New_York"


def test_matcher_outcome_populates_extracted_metadata():
    stream_name = (
        "US - NCAAF 17 : KENTUCKY CHRISTIAN @ MOREHEAD STATE - SEP 3 - 6:00 PM ET / 11:00 PM UK"
    )

    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_db.return_value.__enter__.return_value = mock_conn

    mock_service = MagicMock()
    mock_service.get_provider_name.return_value = "espn"
    mock_service.get_events.return_value = []

    matcher = StreamMatcher(
        service=mock_service,
        db_factory=mock_db,
        group_id=1,
        search_leagues=["college-football"],
        include_leagues=["college-football"],
    )

    results = matcher._match_single(
        stream_id=17,
        stream_name=stream_name,
        target_date=date(2026, 9, 3),
    )
    assert len(results) >= 1
    r = results[0]

    # Pin what carries meaning, not the extraction noise: team1 still includes
    # the provider prefix, and cleaning that up must not break a plumbing test.
    assert "KENTUCKY CHRISTIAN" in (r.parsed_team1 or "")
    assert "MOREHEAD STATE" in (r.parsed_team2 or "")
    assert r.detected_league == "college-football"
    assert r.extracted_date == "2026-09-03"
    assert r.extracted_time == "18:00:00"
    assert r.extracted_tz == "America/New_York"


def test_gated_streams_still_carry_extracted_metadata():
    """A stream turned away by a matching-type gate is exactly the one a user
    inspects in preview, so the early returns must carry metadata too."""
    mock_db = MagicMock()
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None
    mock_conn.execute.return_value.fetchall.return_value = []
    mock_db.return_value.__enter__.return_value = mock_conn

    mock_service = MagicMock()
    mock_service.get_provider_name.return_value = "espn"
    mock_service.get_events.return_value = []

    matcher = StreamMatcher(
        service=mock_service,
        db_factory=mock_db,
        group_id=1,
        search_leagues=["college-football"],
        include_leagues=["college-football"],
        name_match_enabled=False,
    )

    results = matcher._match_single(
        stream_id=17,
        stream_name="US - NCAAF 17 : KENTUCKY CHRISTIAN @ MOREHEAD STATE - SEP 3 - 6:00 PM ET",
        target_date=date(2026, 9, 3),
    )
    r = results[0]

    assert r.exclusion_reason == "name_match_disabled"
    assert "MOREHEAD STATE" in (r.parsed_team2 or "")
    assert r.detected_league == "college-football"
    assert r.extracted_date == "2026-09-03"
    assert r.extracted_time == "18:00:00"


def test_failure_reason_code_matches_run_history_taxonomy():
    """Preview and the run-history drill-down share one reason vocabulary."""

    def code(**kwargs):
        return failure_reason_code(
            MatchedStreamResult(stream_name="s", stream_id=1, matched=False, **kwargs)
        )

    assert code(failed_reason=FailedReason.NO_EVENT_FOUND) == "no_event_found"
    assert code(filtered_reason=FilteredReason.NOT_EVENT) == "filtered:not_event"
    assert code(exclusion_reason="name_match_disabled") == "skipped:name_match_disabled"
    assert code() == "unmatched"
