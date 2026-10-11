"""Every source in a run builds its filler window from one clock reading (#988).

An event channel is shared by every source that matches the event, and each
source writes its own filler for it. The window used to hang off
``datetime.now()`` read per source, so the first block (now − lookback) and
the last (now + 24 h) differed by the seconds between sources. The XMLTV
merge de-duplicates on exact ``(channel, start, stop)``, so those edge blocks
survived: nine "Coming up" programmes seconds apart on one channel.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from teamarr.consumers.event_group_processor import EventGroupProcessor
from teamarr.consumers.filler.event_filler import EventFillerConfig, EventFillerResult
from teamarr.core import Event, EventStatus, Team
from teamarr.utilities.xmltv import merge_xmltv_content, programmes_to_xmltv

TZ = ZoneInfo("America/New_York")
RUN_NOW = datetime(2026, 10, 4, 21, 0, 38, tzinfo=TZ)


def _processor():
    with patch("teamarr.consumers.event_group_processor.processor.create_default_service"):
        return EventGroupProcessor(db_factory=MagicMock())


def _event():
    def team(id_, name):
        return Team(id=id_, provider="espn", name=name, short_name=name, abbreviation=name[:3],
                    league="nfl", sport="football")

    return Event(
        id="401872978", provider="espn", name="Lions at Panthers", short_name="DET @ CAR",
        start_time=datetime(2026, 10, 5, 0, 20, tzinfo=UTC), league="nfl", sport="football",
        status=EventStatus(state="pre"), home_team=team("29", "Panthers"),
        away_team=team("8", "Lions"),
    )


def _windows(processor, clock_readings):
    """Filler windows two sources would build, the wall clock advancing between them."""
    seen = []

    def fake_generate_with_counts(**kwargs):
        seen.append((kwargs["options"].epg_start, kwargs["options"].epg_end))
        return EventFillerResult(programmes=[], pregame_count=0, postgame_count=0)

    stream = {"event": _event(), "feed_team": None, "_exception_keyword": None,
              "segment": None, "segment_start": None, "segment_end": None}
    module = "teamarr.consumers.event_group_processor.xmltv"
    with (
        patch(f"{module}.EventFillerGenerator") as generator,
        patch(f"{module}.get_user_timezone", return_value=TZ),
        patch(f"{module}.datetime") as clock,
    ):
        generator.return_value.generate_with_counts = fake_generate_with_counts
        clock.now.side_effect = lambda tz=None: next(clock_readings)
        for _ in range(2):
            processor._generate_filler_for_streams(
                matched_streams=[stream],
                filler_config=EventFillerConfig(),
                sport_durations={"football": 3.5},
            )
    return seen


def test_two_sources_in_one_run_share_one_filler_window():
    processor = _processor()
    processor._run_now = RUN_NOW
    wall_clock = iter([RUN_NOW + timedelta(seconds=1), RUN_NOW + timedelta(seconds=11)])

    first, second = _windows(processor, wall_clock)

    assert first == second
    assert first == (RUN_NOW - timedelta(hours=6), RUN_NOW + timedelta(days=1))


def test_without_a_run_clock_the_window_follows_the_wall_clock():
    """Direct callers outside process_all_groups keep the old behaviour."""
    processor = _processor()
    assert processor._run_now is None
    wall_clock = iter([RUN_NOW, RUN_NOW + timedelta(seconds=10)])

    first, second = _windows(processor, wall_clock)

    assert second[0] - first[0] == timedelta(seconds=10)


def test_identical_edge_programmes_collapse_in_the_merge():
    """What sharing the window buys: the merge keeps one of each programme."""
    from teamarr.core import Programme

    def source_guide(start):
        programme = Programme(
            channel_id="teamarr-event-401872978", title="Coming up",
            start=start, stop=datetime(2026, 10, 4, 22, 0, tzinfo=UTC),
            description="", filler_type="pregame",
        )
        channels = [{"id": programme.channel_id, "name": "NFL | DET/CAR", "icon": None}]
        return programmes_to_xmltv([programme], channels)

    shared = datetime(2026, 10, 4, 19, 0, 38, tzinfo=UTC)
    merged = merge_xmltv_content([source_guide(shared), source_guide(shared)])
    assert merged.count("<programme ") == 1

    drifting = merge_xmltv_content(
        [source_guide(shared), source_guide(shared + timedelta(seconds=11))]
    )
    assert drifting.count("<programme ") == 2  # the bug: both survive, overlapping
