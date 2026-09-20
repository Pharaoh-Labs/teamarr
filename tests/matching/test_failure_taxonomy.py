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


class TestWindowAndSubscriptionReasons:
    """#791: two failure shapes reported reasons that sent triage nowhere.

    Streams carrying their own future date beyond event_match_days_ahead
    reported NO_EVENT_FOUND with an unrelated near-miss (Stan lists EPL
    matchweek 5 nine days out against a 7-back/3-ahead window), and streams
    whose two sides share only unsubscribed leagues reported
    FIXTURE_NOT_IN_LEAGUE (implying a veto bug) when the honest answer is
    "subscribe that league".
    """

    FUTURE_STREAM = (
        "AU (STAN 94) | Nottingham Forest v Coventry City"
        "  Premier League Matchweek 5 2026/2027 (2026-09-20 02:20:29)"
    )

    def test_future_dated_stream_beyond_window_is_named(self):
        result = _match(self.FUTURE_STREAM, _event(0))
        assert result.failed_reason is FailedReason.EVENT_BEYOND_WINDOW
        assert "beyond" in (result.detail or "")
        assert "+3d" in (result.detail or "")

    def test_future_date_within_window_is_still_no_event_found(self):
        # Tomorrow is inside the +3d window: an unmatched pairing stays the
        # ordinary verdict — beyond-window must not absorb it.
        stream = "Duke vs Clemson @ " + (TODAY + timedelta(days=1)).strftime("%b %d")
        result = _match(stream, _event(0))
        assert result.failed_reason is FailedReason.NO_EVENT_FOUND

    @pytest.fixture
    def soccer_db_factory(self):
        import sqlite3

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE team_cache (
                team_name TEXT, team_short_name TEXT, team_abbrev TEXT,
                league TEXT, sport TEXT)"""
        )
        conn.execute("CREATE TABLE team_aliases (alias TEXT, team_name TEXT, league TEXT)")
        conn.executemany(
            "INSERT INTO team_cache VALUES (?,?,?,?,?)",
            [
                ("Marshall Thundering Herd", "Marshall", "MAR", "usa.ncaa.w.1", "soccer"),
                ("Utah Valley Wolverines", "Utah Valley", "UVU", "usa.ncaa.w.1", "soccer"),
                (
                    "Marshall Thundering Herd",
                    "Marshall",
                    "MAR",
                    "womens-college-volleyball",
                    "volleyball",
                ),
                ("Duke Blue Devils", "Duke", "DUKE", "womens-college-volleyball", "volleyball"),
            ],
        )
        conn.commit()

        class _Factory:
            def __call__(self):
                return self

            def __enter__(self):
                return conn

            def __exit__(self, *exc):
                return False

        return _Factory()

    def _soccer_match(self, db_factory, include_leagues):
        # The candidate is a volleyball game; the stream names the women's
        # soccer fixture. Their only shared league is unsubscribed.
        classified = classify_stream("ESPN+ 95: Utah Valley vs. #20 Marshall @ Sep 11 7:10PM ET")
        matcher = make_team_matcher(db_factory=db_factory, include_leagues=include_leagues)
        ctx = MatchContext(
            stream_name="ESPN+ 95: Utah Valley vs. #20 Marshall @ Sep 11 7:10PM ET",
            stream_id=1,
            group_id=1,
            target_date=TODAY,
            generation=1,
            user_tz=ZoneInfo("UTC"),
            classified=classified,
            team1=classified.team1,
            team2=classified.team2,
        )
        duke = Team(
            id="t-duke",
            provider="espn",
            name="Duke Blue Devils",
            short_name="Duke",
            abbreviation="DUKE",
            league="womens-college-volleyball",
            sport="volleyball",
        )
        marshall = Team(
            id="t-mar",
            provider="espn",
            name="Marshall Thundering Herd",
            short_name="Marshall",
            abbreviation="MAR",
            league="womens-college-volleyball",
            sport="volleyball",
        )
        event = Event(
            id="vb-1",
            provider="espn",
            name="Duke Blue Devils vs Marshall Thundering Herd",
            short_name="Duke vs Marshall",
            start_time=datetime.now(UTC).replace(hour=23),
            home_team=duke,
            away_team=marshall,
            status=EventStatus(state="scheduled"),
            league="womens-college-volleyball",
            sport="volleyball",
        )
        return matcher._match_against_events(ctx, [event], "womens-college-volleyball")

    def test_shared_league_unsubscribed_is_named(self, soccer_db_factory):
        result = self._soccer_match(soccer_db_factory, {"mlb", "eng.1"})
        assert result.failed_reason is FailedReason.FIXTURE_LEAGUE_NOT_SUBSCRIBED
        assert "usa.ncaa.w.1" in (result.detail or "")

    def test_plain_fixture_veto_when_shared_leagues_subscribed(self, soccer_db_factory):
        result = self._soccer_match(soccer_db_factory, {"mlb", "usa.ncaa.w.1"})
        assert result.failed_reason is FailedReason.FIXTURE_NOT_IN_LEAGUE

    def test_unknown_subscription_keeps_plain_fixture_veto(self, soccer_db_factory):
        result = self._soccer_match(soccer_db_factory, None)
        assert result.failed_reason is FailedReason.FIXTURE_NOT_IN_LEAGUE
