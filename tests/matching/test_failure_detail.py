"""A failed match explains itself (#661).

Diagnosing four matching bugs on 2026-08-29 meant reading 1026 JSON records
and re-deriving causes from parsed_team1/parsed_team2 string shapes, because
every failure record shipped with detail NULL. The explanation already existed
— _near_miss_summary computed it — but it went only to a DEBUG log, which the
support bundle truncates to a 256KB tail (78 lines survived out of 11,279).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from teamarr.consumers.matching.classifier import classify_stream
from teamarr.consumers.matching.constants import (
    BOTH_TEAMS_THRESHOLD,
    NEAR_MISS_DETAIL_MAX,
)
from teamarr.core.types import Event, EventStatus, Team
from tests.fakes import make_team_matcher

TZ = ZoneInfo("UTC")


def _team(team_id: str, name: str) -> Team:
    return Team(
        id=team_id,
        provider="espn",
        name=name,
        short_name=name,
        abbreviation="",
        league="college-football",
        sport="football",
    )


def _event(away: str, home: str) -> Event:
    start = datetime.now(UTC) + timedelta(hours=3)
    return Event(
        id="1",
        provider="espn",
        name=f"{away} at {home}",
        short_name=f"{away} at {home}",
        league="college-football",
        sport="football",
        start_time=start,
        home_team=_team("h", home),
        away_team=_team("a", away),
        status=EventStatus(state="scheduled"),
    )


def _matcher(events):
    service = MagicMock()
    service.get_provider_name.return_value = "espn"
    service.get_events.side_effect = lambda league, day, cache_only=False: (
        events if day == datetime.now(UTC).date() else []
    )
    matcher = make_team_matcher(service=service, cache=MagicMock())
    matcher._check_cache = lambda ctx: None
    matcher._cache_result = lambda ctx, result: None
    return matcher


def _fail(stream: str, events):
    matcher = _matcher(events)
    return matcher.match_single_league(
        classify_stream(stream),
        "college-football",
        datetime.now(UTC).date(),
        1,
        1,
        1,
        TZ,
    )


class TestFailedMatchesCarryTheirDiagnosis:
    def test_detail_is_populated(self):
        outcome = _fail(
            "NCAAF 01: Nowhere State at Elsewhere Tech",
            [_event("Robert Morris Colonials", "Wagner Seahawks")],
        )
        assert not outcome.is_matched
        assert outcome.detail

    def test_detail_names_the_closest_candidate_and_both_scores(self):
        outcome = _fail(
            "NCAAF 01: Nowhere State at Elsewhere Tech",
            [_event("Robert Morris Colonials", "Wagner Seahawks")],
        )
        assert "Wagner Seahawks" in outcome.detail
        assert f"need {BOTH_TEAMS_THRESHOLD:.0f}" in outcome.detail
        assert "Nowhere State=" in outcome.detail
        assert "Elsewhere Tech=" in outcome.detail

    def test_empty_window_also_explains_itself(self):
        """This path always set a detail; only persistence dropped it."""
        outcome = _fail("NCAAF 01: Nowhere State at Elsewhere Tech", [])
        assert "No events in college-football" in (outcome.detail or "")

    def test_detail_is_length_capped(self):
        """It ships in every bundle at up to 500 rows per run."""
        from teamarr.consumers.matching.team_matcher import MatchContext

        long_name = "Extremely Long University Of Somewhere " * 6
        event = _event(long_name, long_name)
        matcher = _matcher([event])
        ctx = MatchContext(
            stream_name="s",
            stream_id=1,
            group_id=1,
            target_date=datetime.now(UTC).date(),
            generation=1,
            user_tz=TZ,
            stream_tz=None,
            classified=classify_stream("NCAAF 01: A at B"),
            team1=long_name,
            team2=long_name,
            sport_durations={},
        )
        summary = matcher._near_miss_summary(ctx, [event], long_name, long_name, 0)
        assert len(summary) <= NEAR_MISS_DETAIL_MAX

    def test_summary_does_not_depend_on_debug_logging(self, monkeypatch):
        """It used to early-return unless DEBUG was enabled, so installs that
        raised LOG_LEVEL produced no diagnosis at all."""
        import logging

        from teamarr.consumers.matching import team_matcher

        monkeypatch.setattr(
            team_matcher.logger, "isEnabledFor", lambda level: level >= logging.CRITICAL
        )
        outcome = _fail(
            "NCAAF 01: Nowhere State at Elsewhere Tech",
            [_event("Robert Morris Colonials", "Wagner Seahawks")],
        )
        assert outcome.detail


class TestPersistenceKeepsTheDetail:
    """The column, the dataclass field and the INSERT all existed; the
    FailedMatch(...) construction simply never passed it."""

    def test_detail_reaches_the_failed_match_row(self, db_conn):
        from teamarr.database.stats import (
            FailedMatch,
            create_run,
            get_failed_matches,
            save_failed_matches,
            save_run,
        )

        run = create_run(db_conn, run_type="full_epg")
        run.complete()
        save_run(db_conn, run)
        db_conn.execute(
            "INSERT INTO event_epg_groups (id, name, leagues) VALUES (1, 'NCAAF', '[]')"
        )

        save_failed_matches(
            db_conn,
            [
                FailedMatch(
                    run_id=run.id,
                    group_id=1,
                    group_name="NCAAF",
                    stream_id=1,
                    stream_name="NCAAF 01: A at B",
                    reason="no_event_found",
                    detail="best='X vs Y' scores A=41 / B=41 (need 60)",
                )
            ],
        )
        [row] = get_failed_matches(db_conn, run.id)
        assert row["detail"] == "best='X vs Y' scores A=41 / B=41 (need 60)"

    def test_processor_persists_detail_and_exclusion_reason(self, db_conn):
        """Guards the exact line that was missing: the constructor call.

        `exclusion_reason` was dropped the same way; #662's unmatched rows
        read it to say WHY a stream was left out.
        """
        from teamarr.consumers.event_group_processor.persistence import MatchPersistence
        from teamarr.consumers.matching import BatchMatchResult
        from teamarr.consumers.matching.matcher import MatchedStreamResult
        from teamarr.consumers.matching.result import FailedReason
        from teamarr.database.stats import create_run, get_failed_matches, save_run

        run = create_run(db_conn, run_type="full_epg")
        run.complete()
        save_run(db_conn, run)
        db_conn.execute(
            "INSERT INTO event_epg_groups (id, name, leagues) VALUES (1, 'NCAAF', '[]')"
        )

        result = MatchedStreamResult(
            stream_name="NCAAF 01: A at B",
            stream_id=7,
            matched=False,
            failed_reason=FailedReason.NO_EVENT_FOUND,
            detail="best='X vs Y' scores A=41 / B=41 (need 60)",
            exclusion_reason="no_event_found",
        )
        MatchPersistence()._save_match_details(
            db_conn,
            run_id=run.id,
            group_id=1,
            group_name="NCAAF",
            streams=[{"id": 7, "name": "NCAAF 01: A at B"}],
            match_result=BatchMatchResult(results=[result]),
        )

        [row] = get_failed_matches(db_conn, run.id)
        assert row["detail"] == "best='X vs Y' scores A=41 / B=41 (need 60)"
        assert row["exclusion_reason"] == "no_event_found"
