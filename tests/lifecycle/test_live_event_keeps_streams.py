"""A live event keeps its streams; the cleanup pool is the unfiltered list (#1174).

Providers with numbered event slots (``NHL | 04 - 10pm Maple Leafs at Kraken``)
re-slot every stream for the next day while the evening's last games are
still on. The stream keeps its Dispatcharr id and URL and keeps carrying
tonight's game until it ends; only the name changes. Two gaps let a run
detach it mid-game:

1. ``cleanup_deleted_streams`` never asked whether the channel's event was in
   progress — a stream renamed to tomorrow's game was "rotated", a slot
   blanked to ``NHL | 13 -`` was "no longer in the M3U".
2. The pool was built from the FILTERED stream list, so a renamed slot that
   now fails the built-in filter read as absent. On a matched run that meant
   removal; on the zero-match path (where absence is ignored, #907) it meant
   the finished game's channel kept the stream and played tomorrow's show
   with an empty guide.

Now: while the event is in progress (started and not final, by provider
status when the run saw the event, by the clock and end estimate otherwise)
nothing detaches; the first run after the event applies the verdict. The
pool is the unfiltered M3U list with each stream's filter verdict alongside:
absent = missing (as before), present-but-filtered = an explicit ``filtered``
removal on the normal path (a user's exclude regex still detaches), and only a
changed name on the zero-match path.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from tests.fakes import FakeChannel, FakeStream

GROUP_ID = 42
SLOT_ID = 33639
EVENT = "401892599"  # TOR @ SEA
OTHER_EVENT = "401892610"  # CHI @ DET, tomorrow
TONIGHT = "NHL | 04 - 10pm Maple Leafs at Kraken"
TOMORROW = "NHL | 04 - 7:30pm Blackhawks at Red Wings"
BLANKED = "NHL | 04 -"


def _iso(delta_minutes: int) -> str:
    return (datetime.now(UTC) + timedelta(minutes=delta_minutes)).isoformat()


@pytest.fixture
def service():
    from teamarr.consumers.lifecycle.service import ChannelLifecycleService

    svc = ChannelLifecycleService(
        db_factory=MagicMock(),
        sports_service=MagicMock(),
        channel_manager=MagicMock(),
    )
    svc._remove_stream_from_dispatcharr_channel = MagicMock(return_value=True)
    svc.delete_managed_channel = MagicMock(return_value=True)
    return svc


def _run_cleanup(service, channels, streams_by_channel, current_streams, **kwargs):
    remove = MagicMock()
    history = MagicMock()
    with (
        patch("teamarr.database.channels.get_managed_channels_for_group", return_value=channels),
        patch(
            "teamarr.database.channels.get_channel_streams",
            side_effect=lambda conn, cid, include_removed=False: streams_by_channel.get(cid, []),
        ),
        patch("teamarr.database.channels.remove_stream_from_channel", remove),
        patch("teamarr.database.channels.update_stream_name"),
        patch("teamarr.database.channels.log_channel_history", history),
        patch(
            "teamarr.database.channel_numbers.get_global_consolidation_mode",
            return_value="consolidate",
        ),
    ):
        result = service.cleanup_deleted_streams(GROUP_ID, current_streams, **kwargs)
    return result, remove, history


def _channel(cid=7, *, started_minutes_ago=90, ends_in_minutes=60, event_id=EVENT):
    return FakeChannel(
        id=cid,
        channel_name="Maple Leafs at Kraken",
        event_id=event_id,
        event_date=_iso(-started_minutes_ago),
        event_end_estimate=_iso(ends_in_minutes),
        sport="hockey",
    )


def _slot(name=TONIGHT, sid=SLOT_ID):
    return FakeStream(dispatcharr_stream_id=sid, source_group_id=GROUP_ID, stream_name=name)


def _matched(sid, event_id, name):
    event = MagicMock()
    event.id = event_id
    return {"stream": {"id": sid, "name": name}, "event": event}


# ---------------------------------------------------------------------------
# Case 1 (the report): re-slotted to another event while the game is on
# ---------------------------------------------------------------------------


def test_rotated_stream_stays_while_the_event_is_live(service):
    result, remove, _ = _run_cleanup(
        service,
        channels=[_channel()],
        streams_by_channel={7: [_slot()]},
        current_streams={SLOT_ID: {"id": SLOT_ID, "name": TOMORROW}},
        matched_streams=[_matched(SLOT_ID, OTHER_EVENT, TOMORROW)],
        event_states={EVENT: "live"},
    )

    remove.assert_not_called()
    service.delete_managed_channel.assert_not_called()
    assert result.deleted == []
    assert result.streams_removed == []


def test_rotated_stream_is_detached_once_the_event_is_final(service):
    """The verdict is deferred, not dropped: the first run after the game applies it."""
    result, remove, history = _run_cleanup(
        service,
        channels=[_channel()],
        streams_by_channel={7: [_slot()]},
        current_streams={SLOT_ID: {"id": SLOT_ID, "name": TOMORROW}},
        matched_streams=[_matched(SLOT_ID, OTHER_EVENT, TOMORROW)],
        event_states={EVENT: "final"},
    )

    # Only stream gone → the channel goes (replacement is for another event).
    service.delete_managed_channel.assert_called_once()
    assert len(result.deleted) == 1
    assert "rotated" in result.deleted[0]["reason"]


def test_provider_status_beats_the_clock(service):
    """Overtime: the end estimate has passed but the provider still says live."""
    _, remove, _ = _run_cleanup(
        service,
        channels=[_channel(started_minutes_ago=240, ends_in_minutes=-30)],
        streams_by_channel={7: [_slot()]},
        current_streams={SLOT_ID: {"id": SLOT_ID, "name": TOMORROW}},
        matched_streams=[_matched(SLOT_ID, OTHER_EVENT, TOMORROW)],
        event_states={EVENT: "live"},
    )
    remove.assert_not_called()
    service.delete_managed_channel.assert_not_called()


def test_clock_and_end_estimate_decide_when_the_run_did_not_see_the_event(service):
    """No status for this event this run: started and before the end estimate = in progress."""
    _, remove, _ = _run_cleanup(
        service,
        channels=[_channel()],
        streams_by_channel={7: [_slot()]},
        current_streams={SLOT_ID: {"id": SLOT_ID, "name": TOMORROW}},
        matched_streams=[_matched(SLOT_ID, OTHER_EVENT, TOMORROW)],
        event_states={},
    )
    remove.assert_not_called()
    service.delete_managed_channel.assert_not_called()


def test_postgame_buffer_is_not_live(service):
    """Past the end estimate with no status → not in progress, even though the
    #232 live window (to ``scheduled_delete_at``) would still be open."""
    _run_cleanup(
        service,
        channels=[_channel(started_minutes_ago=240, ends_in_minutes=-30)],
        streams_by_channel={7: [_slot()]},
        current_streams={SLOT_ID: {"id": SLOT_ID, "name": TOMORROW}},
        matched_streams=[_matched(SLOT_ID, OTHER_EVENT, TOMORROW)],
        event_states={},
    )
    service.delete_managed_channel.assert_called_once()


def test_not_started_is_not_live(service):
    """A channel created ahead of kickoff is not protected before the event starts."""
    _run_cleanup(
        service,
        channels=[_channel(started_minutes_ago=-120, ends_in_minutes=60)],
        streams_by_channel={7: [_slot()]},
        current_streams={SLOT_ID: {"id": SLOT_ID, "name": TOMORROW}},
        matched_streams=[_matched(SLOT_ID, OTHER_EVENT, TOMORROW)],
        event_states={EVENT: "scheduled"},
    )
    service.delete_managed_channel.assert_called_once()


def test_missing_stream_is_held_on_a_live_event_too(service):
    """A stream absent from the pool is also deferred mid-game (#1174 second form)."""
    _, remove, _ = _run_cleanup(
        service,
        channels=[_channel()],
        streams_by_channel={7: [_slot()]},
        current_streams={99: {"id": 99, "name": "other"}},
        matched_streams=[_matched(99, OTHER_EVENT, "other")],
        event_states={EVENT: "live"},
    )
    remove.assert_not_called()
    service.delete_managed_channel.assert_not_called()


# ---------------------------------------------------------------------------
# Case 2 (the comment): re-slotted to a non-event name on a zero-match run
# ---------------------------------------------------------------------------


def test_blanked_slot_on_zero_match_run_is_a_content_change_once_the_game_is_over(service):
    """Present in the unfiltered pool under a new name, filtered out, no matches:
    the finished game's channel must not keep playing tomorrow's slot."""
    result, _, _ = _run_cleanup(
        service,
        channels=[_channel(started_minutes_ago=240, ends_in_minutes=-30)],
        streams_by_channel={7: [_slot()]},
        current_streams={SLOT_ID: {"id": SLOT_ID, "name": BLANKED}},
        matched_streams=[],
        changed_only=True,
        filtered_out={SLOT_ID: "not_event"},
        event_states={EVENT: "final"},
    )
    service.delete_managed_channel.assert_called_once()
    assert "content-changed" in result.deleted[0]["reason"]


def test_blanked_slot_on_zero_match_run_is_held_while_the_game_is_on(service):
    _, remove, _ = _run_cleanup(
        service,
        channels=[_channel()],
        streams_by_channel={7: [_slot()]},
        current_streams={SLOT_ID: {"id": SLOT_ID, "name": BLANKED}},
        matched_streams=[],
        changed_only=True,
        filtered_out={SLOT_ID: "not_event"},
        event_states={EVENT: "live"},
    )
    remove.assert_not_called()
    service.delete_managed_channel.assert_not_called()


def test_filter_verdict_alone_is_not_evidence_on_the_zero_match_path(service):
    """Same name, merely filtered this run (a half-configured regex, #450): kept."""
    _, remove, _ = _run_cleanup(
        service,
        channels=[_channel(started_minutes_ago=240, ends_in_minutes=-30)],
        streams_by_channel={7: [_slot()]},
        current_streams={SLOT_ID: {"id": SLOT_ID, "name": TONIGHT}},
        matched_streams=[],
        changed_only=True,
        filtered_out={SLOT_ID: "exclude"},
        event_states={EVENT: "final"},
    )
    remove.assert_not_called()
    service.delete_managed_channel.assert_not_called()


# ---------------------------------------------------------------------------
# Case 3: the normal path keeps today's exclude-regex behaviour, explicitly
# ---------------------------------------------------------------------------


def test_exclude_regex_still_detaches_on_a_matched_run(service):
    """Before #1174 this stream was absent from the filtered pool and removed as
    "no longer exists in M3U". Now it is present, filtered, and removed for that."""
    other = _slot(name="NHL | 05 - Bruins at Wild", sid=44802)
    channel = _channel(started_minutes_ago=240, ends_in_minutes=-30)
    result, remove, history = _run_cleanup(
        service,
        channels=[channel],
        streams_by_channel={7: [_slot(), other]},
        current_streams={
            SLOT_ID: {"id": SLOT_ID, "name": TONIGHT},
            44802: {"id": 44802, "name": other.stream_name},
        },
        matched_streams=[_matched(44802, EVENT, other.stream_name)],
        filtered_out={SLOT_ID: "exclude"},
        event_states={EVENT: "final"},
    )
    remove.assert_called_once()
    assert remove.call_args.args[2] == SLOT_ID
    notes = [c.kwargs.get("notes") for c in history.call_args_list]
    assert any("filtered out: exclude" in (n or "") for n in notes)
    service.delete_managed_channel.assert_not_called()


# ---------------------------------------------------------------------------
# The processor hands cleanup the UNFILTERED pool plus the verdicts
# ---------------------------------------------------------------------------


def test_filter_result_records_per_stream_rejection_reasons():
    from teamarr.services.stream_filter import StreamFilter, StreamFilterConfig

    f = StreamFilter(
        StreamFilterConfig(require_event_pattern=True, exclude_regex="Bruins", exclude_enabled=True)
    )
    result = f.filter(
        [
            {"id": 1, "name": "NHL | 04 - 10pm Maple Leafs at Kraken"},
            {"id": 2, "name": "NHL | 04 -"},
            {"id": 3, "name": "NHL | 05 - Bruins at Wild"},
            {"id": 4, "name": "x", "is_stale": True},
        ]
    )
    assert [s["id"] for s in result.passed] == [1]
    assert result.rejected == {2: "not_event", 3: "exclude", 4: "stale"}


def test_processor_pool_is_the_unfiltered_fetch_with_verdicts(monkeypatch):
    import contextlib
    import sqlite3
    from datetime import date

    from teamarr.consumers.event_group_processor import EventGroupProcessor
    from teamarr.consumers.lifecycle import StreamProcessResult
    from teamarr.consumers.matching.matcher import BatchMatchResult
    from teamarr.database.groups import create_group, get_group
    from teamarr.services.stream_filter import FilterResult
    from tests.helpers import SCHEMA_PATH

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    cur = conn.execute("INSERT INTO templates (name, template_type) VALUES ('T', 'event')")
    conn.execute("INSERT INTO subscription_templates (template_id) VALUES (?)", (cur.lastrowid,))
    gid = create_group(conn, name="NHL", leagues=["nhl"], m3u_group_id=999)
    conn.commit()
    group = get_group(conn, gid)

    @contextlib.contextmanager
    def factory():
        yield conn
        conn.commit()

    proc = EventGroupProcessor(db_factory=factory, service=MagicMock())
    fetched = [
        {"id": 11, "name": TONIGHT},
        {"id": 12, "name": BLANKED},
    ]
    monkeypatch.setattr(proc, "_fetch_streams", lambda g: list(fetched))
    monkeypatch.setattr(
        proc,
        "_filter_streams",
        lambda s, g: (
            [fetched[0]],
            FilterResult(total_input=2, passed_count=1, rejected={12: "not_event"}),
        ),
    )
    monkeypatch.setattr(proc, "_match_streams", lambda *a, **k: BatchMatchResult())
    live_event = MagicMock()
    live_event.id = EVENT
    live_event.status.state = "live"
    proc._shared_events["nhl:2026-10-29"] = ([live_event], False)

    lifecycle = MagicMock()
    lifecycle.process_scheduled_deletions.return_value = StreamProcessResult()
    lifecycle.cleanup_deleted_streams.return_value = StreamProcessResult()
    monkeypatch.setattr(proc, "_get_lifecycle_service", lambda: lifecycle)

    proc._process_group_internal(conn, group, date.today())

    args, kwargs = lifecycle.cleanup_deleted_streams.call_args
    assert args[1] == {11: fetched[0], 12: fetched[1]}
    assert kwargs["filtered_out"] == {12: "not_event"}
    assert kwargs["event_states"] == {EVENT: "live"}
    assert kwargs["changed_only"] is True
