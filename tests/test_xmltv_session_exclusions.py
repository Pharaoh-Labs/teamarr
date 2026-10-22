"""A lifecycle exclusion removes one session's programmes, not the event's (#1117).

A Test is one event with a channel per day. From day 2 on, day 1 is
`event_past`; that verdict used to be keyed on the bare event id and the
XMLTV step dropped every day of the Test with it, so the live day channels
sat without programmes while an ODI from the same template was fine.
"""

from datetime import UTC, datetime, timedelta

from teamarr.consumers.event_group_processor.processor import xmltv_candidates
from teamarr.consumers.lifecycle.timing import ChannelLifecycleManager
from teamarr.consumers.racing_segments import apply_template_race_duration
from teamarr.core.types import Event, EventStatus, RacingSession, Team

DAY1 = datetime(2026, 10, 18, 7, 45, tzinfo=UTC)


def _side(tid: str, name: str) -> Team:
    return Team(
        id=tid,
        provider="espn",
        name=name,
        short_name=name,
        abbreviation=name[:3].upper(),
        league="cricket-test",
        sport="cricket",
    )


def _test_match() -> Event:
    return Event(
        id="1525660",
        provider="espn",
        name="South Africa v Australia",
        short_name="RSA v AUS",
        start_time=DAY1,
        home_team=_side("1", "South Africa"),
        away_team=_side("2", "Australia"),
        status=EventStatus(state="live"),
        league="cricket-test",
        sport="cricket",
        sessions=[
            RacingSession(
                code=f"day{i + 1}", name=f"Day {i + 1}", start_time=DAY1 + timedelta(days=i)
            )
            for i in range(5)
        ],
    )


def _entries(event: Event) -> list[dict]:
    return [
        {
            "stream": {"id": 7, "name": "Sky Sports Cricket"},
            "event": event,
            "segment": s.code,
            "segment_start": s.start_time,
            "segment_end": s.start_time + timedelta(hours=7),
        }
        for s in event.sessions
    ]


def test_a_past_day_removes_only_its_own_programmes():
    event = _test_match()
    excluded = [
        {
            "stream": "Sky Sports Cricket",
            "event_id": event.id,
            "effective_event_id": f"{event.id}-day1",
            "reason": "event_past",
        }
    ]
    kept = xmltv_candidates(_entries(event), excluded)
    assert [m["segment"] for m in kept] == ["day2", "day3", "day4", "day5"]


def test_an_exclusion_without_a_segment_still_removes_the_whole_event():
    event = _test_match()
    odi = Event(**{**event.__dict__, "id": "9", "sessions": []})
    entries = _entries(event) + [{"stream": {"id": 8, "name": "ODI"}, "event": odi}]
    kept = xmltv_candidates(entries, [{"event_id": event.id, "reason": "league_not_included"}])
    assert [m["event"].id for m in kept] == ["9"]


def test_entries_without_an_event_are_dropped():
    assert xmltv_candidates([{"stream": {"id": 1}}], []) == []


def test_a_test_day_takes_the_template_duration():
    event = _test_match()
    match = _entries(event)[1]
    apply_template_race_duration(match, 8.0)
    assert match["segment_end"] == match["segment_start"] + timedelta(hours=8.0)

    manager = ChannelLifecycleManager(
        create_timing="same_day",
        delete_timing="after_event",
        pre_buffer_minutes=60,
        post_buffer_minutes=30,
        default_duration_hours=3.0,
        sport_durations={"cricket": 4.0},
    )
    assert manager.get_event_end_time(event, 8.0, "day2") == DAY1 + timedelta(days=1, hours=8)
    assert manager.get_event_end_time(event, None, "day2") == DAY1 + timedelta(days=1, hours=7)
