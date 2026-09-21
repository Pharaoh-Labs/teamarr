"""A user-selected Skip Stream must suppress future matching (#869)."""

from datetime import date
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.result import FilteredReason
from teamarr.consumers.matching.team_matcher import MatchContext, TeamMatcher
from teamarr.consumers.stream_match_cache import StreamMatchCache


def _context(stream_name="Rays vs Tigers"):
    classified = classify_stream(stream_name)
    return MatchContext(
        stream_name=stream_name,
        stream_id=7,
        group_id=3,
        target_date=date.today(),
        generation=1,
        user_tz=ZoneInfo("UTC"),
        classified=classified,
        team1=classified.team1,
        team2=classified.team2,
    )


def test_user_skip_returns_filtered_outcome_without_rematching(db_factory):
    cache = StreamMatchCache(db_factory)
    cache.set_user_correction(3, 7, "Rays vs Tigers", None, None, {})
    matcher = TeamMatcher(service=None, cache=cache, db_factory=db_factory)

    outcome = matcher._check_cache(_context())

    assert outcome is not None
    assert outcome.is_filtered
    assert outcome.filtered_reason is FilteredReason.USER_SKIPPED
