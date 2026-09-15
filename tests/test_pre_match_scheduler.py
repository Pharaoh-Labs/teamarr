"""Tests for CronScheduler's pre-match/discovery scheduling triggers.

Replaces the old fixed-cron trigger for EPG generation: the scheduler now
wakes up either shortly before the earliest known upcoming match
(pre-match), or after a fallback discovery interval when no upcoming match
is known yet. See teamarr/consumers/scheduler.py.
"""

from datetime import datetime, timedelta

from teamarr.consumers.scheduler import CronScheduler, _parse_event_dt


def _insert_match(db_factory, event_id: str, start: datetime, deleted: bool = False) -> None:
    with db_factory() as conn:
        conn.execute(
            """INSERT INTO managed_channels
                   (event_id, event_provider, tvg_id, channel_name, event_date, deleted_at)
               VALUES (?, 'espn', ?, ?, ?, ?)""",
            (
                event_id,
                f"teamarr-event-{event_id}",
                f"Match {event_id}",
                start.isoformat(),
                "2020-01-01T00:00:00" if deleted else None,
            ),
        )


def _scheduler(db_factory, lead_minutes: int = 30, discovery_hours: int = 4) -> CronScheduler:
    return CronScheduler(
        db_factory=db_factory,
        pre_match_lead_minutes=lead_minutes,
        discovery_interval_hours=discovery_hours,
        run_on_start=False,
    )


class TestParseEventDt:
    def test_parses_aware_iso_string(self):
        assert _parse_event_dt("2026-01-01T00:00:00+00:00") is not None

    def test_parses_naive_string_as_utc(self):
        # Legacy rows have no tz suffix; treated as UTC then converted to local.
        assert _parse_event_dt("2026-01-01T00:00:00") is not None

    def test_returns_none_for_empty(self):
        assert _parse_event_dt(None) is None
        assert _parse_event_dt("") is None

    def test_returns_none_for_garbage(self):
        assert _parse_event_dt("not-a-date") is None


class TestGetNextMatchStart:
    def test_finds_earliest_upcoming_match(self, db_factory):
        now = datetime.now()
        _insert_match(db_factory, "evt-late", now + timedelta(hours=5))
        _insert_match(db_factory, "evt-early", now + timedelta(hours=1))

        sched = _scheduler(db_factory)
        result = sched._get_next_match_start()

        assert result is not None
        event_id, start = result
        assert event_id == "evt-early"

    def test_ignores_past_matches(self, db_factory):
        now = datetime.now()
        _insert_match(db_factory, "evt-past", now - timedelta(hours=1))

        sched = _scheduler(db_factory)
        assert sched._get_next_match_start() is None

    def test_ignores_deleted_channels(self, db_factory):
        now = datetime.now()
        _insert_match(db_factory, "evt-deleted", now + timedelta(hours=1), deleted=True)

        sched = _scheduler(db_factory)
        assert sched._get_next_match_start() is None

    def test_returns_none_when_no_matches(self, db_factory):
        sched = _scheduler(db_factory)
        assert sched._get_next_match_start() is None

    def test_excludes_already_covered_matches(self, db_factory):
        now = datetime.now()
        start = now + timedelta(minutes=10)
        _insert_match(db_factory, "evt-covered", start)

        sched = _scheduler(db_factory)
        # Simulate having already run a pre-match refresh for this exact row.
        sched._pre_match_done.add(("evt-covered", start.isoformat()))

        assert sched._get_next_match_start() is None


class TestComputeNextRun:
    def test_pre_match_wins_when_sooner_than_discovery(self, db_factory):
        now = datetime.now()
        _insert_match(db_factory, "evt-1", now + timedelta(minutes=40))

        sched = _scheduler(db_factory, lead_minutes=30, discovery_hours=4)
        sched._compute_next_run()

        assert sched.next_run_reason == "pre_match"
        # 40 min out, 30 min lead -> fires in ~10 minutes.
        assert sched.next_run is not None
        assert abs((sched.next_run - (now + timedelta(minutes=10))).total_seconds()) < 5

    def test_discovery_wins_when_no_matches_known(self, db_factory):
        sched = _scheduler(db_factory, lead_minutes=30, discovery_hours=4)
        sched._compute_next_run()

        assert sched.next_run_reason == "discovery"
        assert sched.next_run is not None

    def test_discovery_wins_when_match_is_far_away(self, db_factory):
        now = datetime.now()
        _insert_match(db_factory, "evt-far", now + timedelta(days=10))

        sched = _scheduler(db_factory, lead_minutes=30, discovery_hours=4)
        sched._compute_next_run()

        assert sched.next_run_reason == "discovery"

    def test_next_run_immediate_when_lead_window_already_passed(self, db_factory):
        now = datetime.now()
        # Match starts in 5 minutes, but lead time is 30 -> already overdue.
        _insert_match(db_factory, "evt-soon", now + timedelta(minutes=5))

        sched = _scheduler(db_factory, lead_minutes=30, discovery_hours=4)
        sched._compute_next_run()

        assert sched.next_run_reason == "pre_match"
        assert sched.next_run is not None
        assert sched.next_run <= now


class TestMarkPreMatchCovered:
    def test_covers_matches_within_lead_window(self, db_factory):
        now = datetime.now()
        _insert_match(db_factory, "evt-a", now + timedelta(minutes=10))
        _insert_match(db_factory, "evt-b", now + timedelta(minutes=25))
        _insert_match(db_factory, "evt-c", now + timedelta(hours=3))

        sched = _scheduler(db_factory, lead_minutes=30)
        sched._mark_pre_match_covered()

        assert sched._get_next_match_start()[0] == "evt-c"

    def test_slate_of_same_time_matches_covered_by_one_run(self, db_factory):
        """A Sunday-1pm-style slate should only need one pre-match run."""
        now = datetime.now()
        start = now + timedelta(minutes=15)
        for i in range(5):
            _insert_match(db_factory, f"evt-slate-{i}", start)

        sched = _scheduler(db_factory, lead_minutes=30)
        sched._mark_pre_match_covered()

        assert sched._get_next_match_start() is None
