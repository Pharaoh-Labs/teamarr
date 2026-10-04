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


# ---------------------------------------------------------------------------
# Every match path (#869, reopened)
#
# The fix above lived in the team-vs-team matcher, so a skip on any other kind
# of stream did nothing: team streams never read the cache, guide-anchored
# matches bypass it, and the event-card, racing and tennis matchers deleted the
# skip row because it cannot be rebuilt into an event. The reporter's stream,
# `US: SPORTSNET NEW YORK HD`, is a team stream.
# ---------------------------------------------------------------------------

import pytest  # noqa: E402

from teamarr.consumers.matching.event_matcher import (  # noqa: E402
    EventCardMatcher,
    EventMatchContext,
)
from teamarr.consumers.matching.matcher import StreamMatcher  # noqa: E402
from teamarr.consumers.matching.racing_matcher import (  # noqa: E402
    RacingMatchContext,
    RacingMatcher,
)
from teamarr.consumers.matching.result import FailedReason, MatchOutcome  # noqa: E402
from teamarr.consumers.matching.tennis_matcher import (  # noqa: E402
    TennisMatchContext,
    TennisMatcher,
)

GROUP = 3

# One stream per way a stream can be matched.
STREAMS = {
    "team stream": "US: SPORTSNET NEW YORK HD",
    "team vs team": "Rays vs Tigers",
    "event card": "UFC 320: Main Card",
    "racing": "F1: Singapore Grand Prix",
    "unclassifiable": "ESPN",
}


def _stream_matcher(db_factory, group_id=GROUP, **kw):
    matcher = StreamMatcher(
        service=None, db_factory=db_factory, group_id=group_id, search_leagues=["nhl"],
        include_leagues=["nhl"], include_final_events=False, sport_durations={},
        generation=7, shared_events={}, name_match_enabled=True,
        team_streams_enabled=True, **kw,
    )
    # Anything that reaches routing is, for these tests, a stream that was matched
    matcher.routed = []

    def route(classified, stream_id, target_date):
        matcher.routed.append(stream_id)
        return [MatchOutcome.failed(FailedReason.NO_EVENT_FOUND, stream_id=stream_id)]

    matcher._route_to_outcomes = route
    matcher._try_mixed_group_fallbacks = lambda *a, **k: None
    return matcher


def _skip(db_factory, name, stream_id=7, group_id=GROUP):
    StreamMatchCache(db_factory).set_user_correction(group_id, stream_id, name, None, None, {})


def _rows(db_factory):
    with db_factory() as conn:
        return {
            r["stream_name"]: r["event_id"]
            for r in conn.execute("SELECT stream_name, event_id FROM stream_match_cache")
        }


@pytest.mark.parametrize("kind", sorted(STREAMS))
def test_a_skip_holds_on_every_match_path(db_factory, kind):
    name = STREAMS[kind]
    _skip(db_factory, name)
    matcher = _stream_matcher(db_factory)

    results = matcher._match_single(7, name, date.today())

    assert [r.filtered_reason for r in results] == [FilteredReason.USER_SKIPPED]
    assert results[0].matched is False and results[0].included is False
    assert matcher.routed == []


def test_an_unskipped_stream_is_still_matched(db_factory):
    _skip(db_factory, STREAMS["team stream"])
    matcher = _stream_matcher(db_factory)

    matcher._match_single(8, "NHL | New York Rangers", date.today())

    assert matcher.routed == [8]


def test_a_skip_belongs_to_its_own_source(db_factory):
    """The same stream in another source is a different decision."""
    _skip(db_factory, STREAMS["team stream"], group_id=99)
    matcher = _stream_matcher(db_factory)

    matcher._match_single(7, STREAMS["team stream"], date.today())

    assert matcher.routed == [7]


def test_a_skipped_stream_is_not_matched_through_its_guide_either(db_factory):
    name = STREAMS["team stream"]
    _skip(db_factory, name)
    matcher = _stream_matcher(db_factory)
    matcher._epg_index = object()
    guide_lookups = []
    matcher._match_via_epg = lambda **kw: guide_lookups.append(kw["stream_id"]) or []
    matcher._reconcile_epg = lambda results, epg, tvg_id: results

    result = matcher.match_all(
        [
            {"id": 7, "name": name, "tvg_id": "sny.us"},
            {"id": 8, "name": "ESPN", "tvg_id": "espn.us"},
        ],
        date.today(),
    )

    assert guide_lookups == [8]
    by_id = {r.stream_id: r for r in result.results}
    assert by_id[7].filtered_reason is FilteredReason.USER_SKIPPED


def test_removing_the_skip_takes_effect_on_the_next_batch(db_factory):
    name = STREAMS["team stream"]
    _skip(db_factory, name)
    matcher = _stream_matcher(db_factory)
    stream = [{"id": 7, "name": name}]

    matcher.match_all(stream, date.today())
    assert matcher.routed == []

    StreamMatchCache(db_factory).delete(GROUP, 7, name)
    matcher.match_all(stream, date.today())
    assert matcher.routed == [7]


@pytest.mark.parametrize(
    ("name", "check"),
    [
        (
            "UFC 320: Main Card",
            lambda cache, base: EventCardMatcher(None, cache)._check_cache(
                EventMatchContext(**base)
            ),
        ),
        (
            "F1: Singapore Grand Prix",
            lambda cache, base: RacingMatcher(None, cache)._check_cache(
                RacingMatchContext(**base)
            ),
        ),
        (
            "US Open: Sinner vs Alcaraz",
            lambda cache, base: TennisMatcher(None, cache)._check_cache(
                TennisMatchContext(**base)
            ),
        ),
    ],
    ids=["event card", "racing", "tennis"],
)
def test_a_matcher_never_deletes_the_users_row(db_factory, name, check):
    """These three used to delete a skip because it holds no event to rebuild."""
    cache = StreamMatchCache(db_factory)
    cache.set_user_correction(GROUP, 7, name, None, None, {})
    base = dict(
        stream_name=name, stream_id=7, group_id=GROUP, target_date=date.today(),
        generation=1, user_tz=ZoneInfo("UTC"), classified=classify_stream(name),
    )

    assert check(cache, base) is None
    assert _rows(db_factory) == {name: "__SKIPPED__"}
