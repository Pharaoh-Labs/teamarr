"""Tests for CronScheduler's pre-match/discovery scheduling triggers.

Covers the event-driven scheduling mode for EPG generation: the scheduler
wakes up either shortly before the earliest known upcoming match
(pre-match, with an optional per-sport lead time override), or after a
fallback discovery interval when no upcoming match is known yet. See
teamarr/consumers/scheduler.py. (The classic fixed-cron mode is covered
separately in tests/subscriptions/test_sub_scheduler.py.)
"""

from datetime import datetime, timedelta

from teamarr.consumers.scheduler import CronScheduler, _parse_event_dt
from teamarr.database.sport_schedule import upsert_sport_lead_override


def _insert_match(
    db_factory,
    event_id: str,
    start: datetime,
    sport: str = "football",
    deleted: bool = False,
) -> None:
    with db_factory() as conn:
        conn.execute(
            """INSERT INTO managed_channels
                   (event_id, event_provider, tvg_id, channel_name, event_date, sport, deleted_at)
               VALUES (?, 'espn', ?, ?, ?, ?, ?)""",
            (
                event_id,
                f"teamarr-event-{event_id}",
                f"Match {event_id}",
                start.isoformat(),
                sport,
                "2020-01-01T00:00:00" if deleted else None,
            ),
        )


def _scheduler(db_factory, lead_minutes: int = 30, discovery_hours: int = 4) -> CronScheduler:
    return CronScheduler(
        db_factory=db_factory,
        mode="pre_match",
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


class TestGetNextTrigger:
    def test_finds_soonest_trigger(self, db_factory):
        now = datetime.now()
        _insert_match(db_factory, "evt-late", now + timedelta(hours=5))
        _insert_match(db_factory, "evt-early", now + timedelta(hours=1))

        sched = _scheduler(db_factory)
        result = sched._get_next_trigger()

        assert result is not None
        assert result.event_id == "evt-early"

    def test_ignores_past_matches(self, db_factory):
        now = datetime.now()
        _insert_match(db_factory, "evt-past", now - timedelta(hours=1))

        sched = _scheduler(db_factory)
        assert sched._get_next_trigger() is None

    def test_ignores_deleted_channels(self, db_factory):
        now = datetime.now()
        _insert_match(db_factory, "evt-deleted", now + timedelta(hours=1), deleted=True)

        sched = _scheduler(db_factory)
        assert sched._get_next_trigger() is None

    def test_returns_none_when_no_matches(self, db_factory):
        sched = _scheduler(db_factory)
        assert sched._get_next_trigger() is None

    def test_excludes_already_covered_matches(self, db_factory):
        now = datetime.now()
        start = now + timedelta(minutes=10)
        _insert_match(db_factory, "evt-covered", start)

        sched = _scheduler(db_factory)
        # Simulate having already run a pre-match refresh for this exact row.
        sched._pre_match_done.add(("evt-covered", start.isoformat()))

        assert sched._get_next_trigger() is None


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

    def test_next_match_start_and_sport_populated(self, db_factory):
        now = datetime.now()
        _insert_match(db_factory, "evt-1", now + timedelta(minutes=40), sport="mma")

        sched = _scheduler(db_factory, lead_minutes=30)
        sched._compute_next_run()

        assert sched.next_match_sport == "mma"
        assert sched.next_match_start is not None


class TestMarkPreMatchCovered:
    def test_covers_matches_within_lead_window(self, db_factory):
        now = datetime.now()
        _insert_match(db_factory, "evt-a", now + timedelta(minutes=10))
        _insert_match(db_factory, "evt-b", now + timedelta(minutes=25))
        _insert_match(db_factory, "evt-c", now + timedelta(hours=3))

        sched = _scheduler(db_factory, lead_minutes=30)
        sched._mark_pre_match_covered()

        assert sched._get_next_trigger().event_id == "evt-c"

    def test_slate_of_same_time_matches_covered_by_one_run(self, db_factory):
        """A Sunday-1pm-style slate should only need one pre-match run."""
        now = datetime.now()
        start = now + timedelta(minutes=15)
        for i in range(5):
            _insert_match(db_factory, f"evt-slate-{i}", start)

        sched = _scheduler(db_factory, lead_minutes=30)
        sched._mark_pre_match_covered()

        assert sched._get_next_trigger() is None


class TestPerSportLeadTimes:
    def test_sport_override_changes_trigger_time(self, db_factory):
        now = datetime.now()
        _insert_match(db_factory, "evt-nfl", now + timedelta(hours=2), sport="football")

        with db_factory() as conn:
            upsert_sport_lead_override(conn, "football", 90)

        sched = _scheduler(db_factory, lead_minutes=30)
        result = sched._get_next_trigger()

        assert result is not None
        # 90 min override, not the global 30 min default.
        expected = now + timedelta(hours=2) - timedelta(minutes=90)
        assert abs((result.trigger_time - expected).total_seconds()) < 5

    def test_longer_sport_lead_can_fire_before_earlier_raw_start(self, db_factory):
        """A later-starting match with a longer lead can trigger first."""
        now = datetime.now()
        # Soccer match starts sooner (1h out) but has the default 30 min lead.
        _insert_match(db_factory, "evt-soccer", now + timedelta(hours=1), sport="soccer")
        # NFL match starts later (2h out) but has a 100 min override lead,
        # so its trigger time (2h - 100min = 20min out) is sooner.
        _insert_match(db_factory, "evt-nfl", now + timedelta(hours=2), sport="football")

        with db_factory() as conn:
            upsert_sport_lead_override(conn, "football", 100)

        sched = _scheduler(db_factory, lead_minutes=30)
        result = sched._get_next_trigger()

        assert result is not None
        assert result.event_id == "evt-nfl"

    def test_sports_without_override_use_global_default(self, db_factory):
        now = datetime.now()
        _insert_match(db_factory, "evt-soccer", now + timedelta(minutes=40), sport="soccer")

        with db_factory() as conn:
            upsert_sport_lead_override(conn, "football", 90)  # different sport

        sched = _scheduler(db_factory, lead_minutes=30)
        result = sched._get_next_trigger()

        assert result is not None
        expected = now + timedelta(minutes=40) - timedelta(minutes=30)
        assert abs((result.trigger_time - expected).total_seconds()) < 5

    def test_mark_covered_respects_per_sport_lead(self, db_factory):
        now = datetime.now()
        # Within the football override's 90 min lead, but outside the global 30.
        _insert_match(db_factory, "evt-nfl", now + timedelta(minutes=60), sport="football")

        with db_factory() as conn:
            upsert_sport_lead_override(conn, "football", 90)

        sched = _scheduler(db_factory, lead_minutes=30)
        sched._mark_pre_match_covered()

        assert sched._get_next_trigger() is None

    def test_override_takes_effect_without_restart(self, db_factory):
        """Overrides are read fresh from the DB on every computation."""
        now = datetime.now()
        _insert_match(db_factory, "evt-nfl", now + timedelta(minutes=60), sport="football")

        sched = _scheduler(db_factory, lead_minutes=30)
        # Before the override: 60 min out, 30 min global lead -> not yet due.
        before = sched._get_next_trigger()
        assert before is not None
        assert before.trigger_time > now

        with db_factory() as conn:
            upsert_sport_lead_override(conn, "football", 90)

        # Same scheduler instance, no restart — override applies immediately.
        after = sched._get_next_trigger()
        assert after is not None
        assert after.trigger_time <= now


class TestCronMode:
    """The classic fixed-cron mode, restored alongside pre_match as an option."""

    def test_compute_next_run_uses_cron_expression(self, db_factory):
        sched = CronScheduler(
            db_factory=db_factory,
            mode="cron",
            cron_expression="0 * * * *",  # every hour on the hour
            run_on_start=False,
        )
        sched._compute_next_run()

        assert sched.next_run_reason == "cron"
        assert sched.next_run is not None
        assert sched.next_run.minute == 0
        assert sched.next_run.second == 0

    def test_cron_mode_ignores_known_matches(self, db_factory):
        """Cron mode fires on schedule regardless of any known upcoming match."""
        now = datetime.now()
        _insert_match(db_factory, "evt-soon", now + timedelta(minutes=1))

        sched = CronScheduler(
            db_factory=db_factory,
            mode="cron",
            cron_expression="0 0 1 1 *",  # once a year — never fires in a test run
            run_on_start=False,
        )
        sched._compute_next_run()

        assert sched.next_run_reason == "cron"
        assert sched.next_match_start is None
        assert sched.next_match_sport is None

    def test_start_rejects_invalid_cron_expression(self, db_factory):
        sched = CronScheduler(
            db_factory=db_factory,
            mode="cron",
            cron_expression="not a cron",
            run_on_start=False,
        )
        assert not sched.start()
        assert not sched.is_running

    def test_start_accepts_valid_cron_expression(self, db_factory):
        sched = CronScheduler(
            db_factory=db_factory,
            mode="cron",
            cron_expression="0 0 1 1 *",
            run_on_start=False,
        )
        try:
            assert sched.start()
            assert sched.is_running
        finally:
            sched.stop(timeout=5.0)

    def test_invalid_mode_falls_back_to_pre_match(self, db_factory):
        sched = CronScheduler(db_factory=db_factory, mode="bogus", run_on_start=False)
        assert sched.mode == "pre_match"
