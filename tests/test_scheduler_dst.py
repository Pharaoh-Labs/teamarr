"""The scheduler reads an aware clock, so a DST change neither skips nor stalls a slot (#1185).

Before, both cron loops fed croniter a naive ``datetime.now()``. At fall-back
the run at the first 01:00 computed "next run 02:00"; the wall clock then went
back to 01:00, the wait stretched by an hour, and the repeated 01:00 never
fired (prod lost the 06:00 UTC run on 2026-11-01). Spring-forward is the
mirror: a slot in the hour the clock skips. These tests drive the pure
``next_cron_run`` helper the loops call, with no threads or sleeps.
"""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from teamarr.config import Config
from teamarr.consumers.scheduler import (
    generation_due_this_minute,
    next_cron_run,
    scheduler_now,
    scheduler_timezone,
    seconds_until,
)

NY = ZoneInfo("America/New_York")
UTC = ZoneInfo("UTC")


def _walk(cron: str, start: datetime, count: int) -> list[datetime]:
    runs = []
    now = start
    for _ in range(count):
        now = next_cron_run(cron, now)
        runs.append(now)
    return runs


def test_hourly_cron_fires_both_one_oclocks_at_fall_back():
    runs = _walk("0 * * * *", datetime(2026, 11, 1, 0, 30, tzinfo=NY), 3)

    assert [r.astimezone(UTC) for r in runs] == [
        datetime(2026, 11, 1, 5, 0, tzinfo=UTC),  # 01:00 EDT
        datetime(2026, 11, 1, 6, 0, tzinfo=UTC),  # 01:00 EST — the hour that was lost
        datetime(2026, 11, 1, 7, 0, tzinfo=UTC),  # 02:00 EST
    ]
    assert [r.tzname() for r in runs] == ["EDT", "EST", "EST"]
    # Three consecutive REAL hours: no stretched wait between any two. The wait
    # the loop sleeps is measured the same way, in epoch seconds — a wall-clock
    # subtraction of two datetimes sharing a tzinfo ignores the fold and would
    # read "01:00 EST minus 01:00 EDT" as zero.
    assert all(seconds_until(b, a) == 3600 for a, b in zip(runs, runs[1:], strict=False))
    assert seconds_until(runs[1], runs[0]) == 3600
    assert (runs[1] - runs[0]) == timedelta(0)  # the trap the helper exists for


def test_hourly_cron_steps_over_the_missing_hour_at_spring_forward():
    runs = _walk("0 * * * *", datetime(2026, 3, 8, 0, 30, tzinfo=NY), 2)

    assert runs[0] == datetime(2026, 3, 8, 1, 0, tzinfo=NY)
    assert runs[0].tzname() == "EST"
    assert runs[1].tzname() == "EDT"
    assert runs[1].hour == 3  # 02:00 does not exist on the wall clock
    assert seconds_until(runs[1], runs[0]) == 3600  # one real hour, not two
    assert runs[1] - runs[0] == timedelta(hours=2)  # what a wall-clock subtraction says


def test_daily_slot_inside_the_skipped_hour_runs_right_after_the_jump():
    nxt = next_cron_run("30 2 * * *", datetime(2026, 3, 7, 12, 0, tzinfo=NY))
    assert nxt == datetime(2026, 3, 8, 3, 0, tzinfo=NY)
    assert nxt.tzname() == "EDT"


def test_generation_due_this_minute_reads_the_repeated_hour_too():
    # The scan's same-minute check (#1081) uses the same aware clock, so the
    # second 01:00 is a due minute like the first.
    assert generation_due_this_minute("0 * * * *", datetime(2026, 11, 1, 1, 0, 3, tzinfo=NY))
    second_one = datetime(2026, 11, 1, 6, 0, 3, tzinfo=UTC).astimezone(NY)
    assert second_one.tzname() == "EST"
    assert generation_due_this_minute("0 * * * *", second_one)
    assert not generation_due_this_minute("0 * * * *", datetime(2026, 11, 1, 1, 1, 3, tzinfo=NY))


def test_scheduler_clock_is_the_ui_timezone(monkeypatch):
    # TZ set and valid → that zone, the one the user sees next to the schedule.
    monkeypatch.setattr(Config, "_ui_timezone_from_env", "America/New_York")
    assert scheduler_timezone().key == "America/New_York"
    now = scheduler_now()
    assert now.tzinfo is not None and now.utcoffset() is not None
    assert next_cron_run("0 * * * *", now).tzinfo is not None

    # TZ unset or invalid → the EPG timezone, exactly as the UI falls back.
    monkeypatch.setattr(Config, "_ui_timezone_from_env", "Not/AZone")
    assert scheduler_timezone().key == Config.get_timezone_str()
    monkeypatch.setattr(Config, "_ui_timezone_from_env", None)
    assert scheduler_timezone().key == Config.get_timezone_str()
