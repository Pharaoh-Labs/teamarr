"""Failure records say why (#662).

38% of one install's persisted "failures" carried the literal string
"unmatched" — not a FailedReason, just persistence's catch-all for anything
that was neither matched nor an exception. Those rows were filter verdicts and
per-source skips, not match failures. And `no_event_found` absorbed candidates
that were never scored at all (outside the search window, past the EPG anchor,
sport-hint mismatch), while the near-miss summary printed 100/100 for one of
them — sending triage after the fixture gate for a window miss.
"""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.result import FailedReason, FilteredReason, ResultCategory
from teamarr.consumers.matching.team_matcher import MatchContext
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

TODAY = datetime.now(UTC).date()


def _team(name: str, abbr: str) -> Team:
    return Team(
        id=f"t-{abbr}",
        provider="espn",
        name=name,
        short_name=name,
        abbreviation=abbr,
        league="college-football",
        sport="football",
    )


def _event(days_from_today: int, sport: str = "football") -> Event:
    start = datetime.combine(TODAY, datetime.min.time(), tzinfo=UTC) + timedelta(
        days=days_from_today, hours=23
    )
    return Event(
        id=f"e{days_from_today}",
        provider="espn",
        name="Wagner Seahawks at Robert Morris Colonials",
        short_name="WAG at RMU",
        start_time=start,
        home_team=_team("Robert Morris Colonials", "RMU"),
        away_team=_team("Wagner Seahawks", "WAG"),
        status=EventStatus(state="scheduled"),
        league="college-football",
        sport=sport,
    )


def _match(stream: str, event: Event, *, anchor=None):
    classified = classify_stream(stream)
    matcher = make_team_matcher()
    ctx = MatchContext(
        stream_name=stream,
        stream_id=1,
        group_id=1,
        target_date=TODAY,
        generation=1,
        user_tz=ZoneInfo("UTC"),
        classified=classified,
        team1=classified.team1,
        team2=classified.team2,
        anchor_dt=anchor,
    )
    return matcher._match_against_events(ctx, [event], "college-football")


class TestGatedCandidatesAreNamed:
    def test_scoring_still_matches_the_in_window_event(self):
        result = _match("Wagner vs Robert Morris", _event(0))
        assert result.category is ResultCategory.MATCHED

    def test_only_candidate_outside_search_window_is_gated_not_no_event(self):
        """Both sides would score 100 — the loop just never looked."""
        result = _match("Wagner vs Robert Morris", _event(-45))
        assert result.failed_reason is FailedReason.CANDIDATES_GATED
        assert "gated=1" in (result.detail or "")

    def test_only_candidate_past_epg_anchor_tolerance_is_gated(self):
        event = _event(0)
        anchor = event.start_time + timedelta(hours=6)
        result = _match("Wagner vs Robert Morris", event, anchor=anchor)
        assert result.failed_reason is FailedReason.CANDIDATES_GATED

    def test_sport_hint_mismatch_is_gated(self):
        # "Basketball:" gives a sport hint with no league hint; the candidate is football.
        result = _match("Basketball: Wagner vs Robert Morris", _event(0))
        assert result.failed_reason is FailedReason.CANDIDATES_GATED

    def test_scored_but_low_candidate_is_still_no_event_found(self):
        result = _match("Duke vs Clemson", _event(0))
        assert result.failed_reason is FailedReason.NO_EVENT_FOUND

    def test_near_miss_reads_only_scored_candidates(self):
        """A gated event must not show up as a 100/100 near miss."""
        result = _match("Wagner vs Robert Morris", _event(-45))
        assert "100" not in (result.detail or "")


class TestPersistedReasonsAreHonest:
    @pytest.fixture
    def run_and_group(self, db_conn):
        from teamarr.database.stats import create_run, save_run

        run = create_run(db_conn, run_type="full_epg")
        run.complete()
        save_run(db_conn, run)
        db_conn.execute("INSERT INTO event_epg_groups (id, name, leagues) VALUES (1, 'G', '[]')")
        return run

    def _persist(self, db_conn, run, results):
        from teamarr.consumers.event_group_processor.persistence import MatchPersistence
        from teamarr.consumers.matching import BatchMatchResult
        from teamarr.database.stats import get_failed_matches

        MatchPersistence()._save_match_details(
            db_conn,
            run_id=run.id,
            group_id=1,
            group_name="G",
            streams=[{"id": r.stream_id, "name": r.stream_name} for r in results],
            match_result=BatchMatchResult(results=list(results)),
        )
        return {row["stream_id"]: row["reason"] for row in get_failed_matches(db_conn, run.id)}

    def test_filter_and_skip_outcomes_are_not_unmatched(self, db_conn, run_and_group):
        from teamarr.consumers.matching.matcher import MatchedStreamResult

        results = [
            MatchedStreamResult(
                stream_name="ESPN",
                stream_id=1,
                matched=False,
                exclusion_reason="unclassifiable",
            ),
            MatchedStreamResult(
                stream_name="NFL: A vs B",
                stream_id=2,
                matched=False,
                exclusion_reason="name_match_disabled",
            ),
            MatchedStreamResult(
                stream_name="Bills",
                stream_id=3,
                matched=False,
                exclusion_reason="team_streams_disabled",
            ),
            MatchedStreamResult(
                stream_name="News Hour",
                stream_id=4,
                matched=False,
                filtered_reason=FilteredReason.NOT_EVENT,
                exclusion_reason="not_event",
            ),
            MatchedStreamResult(
                stream_name="NHL: A vs B",
                stream_id=5,
                matched=False,
                filtered_reason=FilteredReason.LEAGUE_NOT_INCLUDED,
                exclusion_reason="league_not_included",
            ),
            MatchedStreamResult(
                stream_name="A vs B",
                stream_id=6,
                matched=False,
                failed_reason=FailedReason.NO_EVENT_FOUND,
                exclusion_reason="no_event_found",
            ),
        ]
        reasons = self._persist(db_conn, run_and_group, results)
        assert reasons == {
            1: "skipped:unclassifiable",
            2: "skipped:name_match_disabled",
            3: "skipped:team_streams_disabled",
            4: "filtered:not_event",
            5: "filtered:league_not_included",
            6: "no_event_found",
        }
        assert "unmatched" not in reasons.values()

    def test_placeholder_and_unsupported_sport_are_still_not_persisted(
        self, db_conn, run_and_group
    ):
        from teamarr.consumers.matching.matcher import MatchedStreamResult

        results = [
            MatchedStreamResult(
                stream_name="---", stream_id=1, matched=False, exclusion_reason="placeholder"
            ),
            MatchedStreamResult(
                stream_name="Diving",
                stream_id=2,
                matched=False,
                exclusion_reason="sport_not_supported",
            ),
        ]
        assert self._persist(db_conn, run_and_group, results) == {}
