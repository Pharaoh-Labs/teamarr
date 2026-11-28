"""A stream the user removes from a channel stays off it (#1173, #1160).

Deleting a stream in Dispatcharr never stuck: Teamarr still listed the stream
on the channel and the next run pushed it back. Remove on the dashboard now
detaches the stream and leaves its soft-removed row marked ``user_removed``.
That row is the exclusion. Every path that puts a stream on a channel asks
for it first:

* the creator's consolidate add,
* the settings sync's stream drift fix,
* keyword enforcement's move to a target channel,
* the team-channel membership reconcile (scoped to the game).

The marker is per channel, so the same stream still attaches elsewhere, and
it goes with the channel. Undo brings the stream back.

A "no event" correction (#1160) is the same kind of statement made on the
Matching page: the matcher stopped matching the stream, but nothing detached
it from the channel it was already on.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from teamarr.consumers.enforcement.keywords import KeywordEnforcer
from teamarr.consumers.lifecycle.service import ChannelLifecycleService
from teamarr.consumers.lifecycle.types import StreamProcessResult
from teamarr.consumers.stream_match_cache import StreamMatchCache
from teamarr.database.channels import (
    USER_REMOVED_REASON,
    add_stream_to_channel,
    create_managed_channel,
    get_channel_streams,
    get_managed_channel,
    get_ordered_stream_ids,
    get_user_removed_streams,
    remove_stream_from_channel,
    restore_user_removed_stream,
    stream_removed_by_user,
)
from teamarr.database.groups import create_group
from teamarr.database.managed_team_channel_streams import (
    active_stream_ids,
    get_user_removed_team_streams,
    reconcile_team_streams,
)
from teamarr.dispatcharr.types import DispatcharrChannel, OperationResult
from teamarr.services import channel_stream_exclusion as exclusion
from tests.fakes import FakeEvent

EVENT = "401872964"
DISP_ID = 900
GOOD = 111
BAD = 222


def _stamp(delta_minutes: int) -> str:
    return (datetime.now(UTC) + timedelta(minutes=delta_minutes)).strftime("%Y-%m-%d %H:%M:%S")


def _channel(conn, group_id, *, keyword=None, event_id=EVENT, disp_id=DISP_ID, **extra):
    return create_managed_channel(
        conn=conn,
        event_epg_group_id=group_id,
        event_id=event_id,
        event_provider="espn",
        tvg_id=f"tvg-{event_id}-{keyword or 'main'}",
        channel_name=f"NFL | PIT/CLE{f' ({keyword})' if keyword else ''}",
        exception_keyword=keyword,
        dispatcharr_channel_id=disp_id,
        **extra,
    )


def _attach(conn, channel_id, stream_id, name=None, source_group_id=None, **extra):
    add_stream_to_channel(
        conn=conn,
        managed_channel_id=channel_id,
        dispatcharr_stream_id=stream_id,
        stream_name=name or f"Feed {stream_id}",
        priority=0,
        source_group_id=source_group_id,
        **extra,
    )


def _live_ids(conn, channel_id):
    return [s.dispatcharr_stream_id for s in get_channel_streams(conn, channel_id)]


def _remote(streams, disp_id=DISP_ID):
    return DispatcharrChannel(
        id=disp_id,
        uuid=f"uuid-{disp_id}",
        name="NFL | PIT/CLE",
        channel_number="5001",
        tvg_id="tvg",
        channel_group_id=None,
        logo_id=None,
        logo_url=None,
        streams=tuple(streams),
        stream_profile_id=None,
    )


def _channel_manager(streams, *, accepts=True):
    cm = MagicMock()
    cm.get_channel.return_value = _remote(streams)
    cm.get_channel_existence.return_value = (_remote(streams), False)
    cm.update_channel.return_value = OperationResult(
        success=accepts, error=None if accepts else "500"
    )
    return cm


@pytest.fixture
def seeded(db_factory):
    """One event channel carrying a good and a bad stream."""
    with db_factory() as conn:
        group_id = create_group(conn, name="NFL Game Pass", leagues=["nfl"])
        channel_id = _channel(conn, group_id)
        _attach(conn, channel_id, GOOD, source_group_id=group_id)
        _attach(conn, channel_id, BAD, source_group_id=group_id)
    return group_id, channel_id


# ---------------------------------------------------------------------------
# The marker
# ---------------------------------------------------------------------------


def test_only_a_user_removal_is_an_exclusion(db_factory, seeded):
    _, channel_id = seeded
    with db_factory() as conn:
        remove_stream_from_channel(conn, channel_id, GOOD, reason="event_rotated")
        remove_stream_from_channel(conn, channel_id, BAD, reason=USER_REMOVED_REASON)

        assert not stream_removed_by_user(conn, channel_id, GOOD)
        assert stream_removed_by_user(conn, channel_id, BAD)
        assert [s.dispatcharr_stream_id for s in get_user_removed_streams(conn, channel_id)] == [
            BAD
        ]


def test_undo_brings_back_one_row_and_clears_the_marker(db_factory, seeded):
    _, channel_id = seeded
    with db_factory() as conn:
        remove_stream_from_channel(conn, channel_id, BAD, reason=USER_REMOVED_REASON)
        assert restore_user_removed_stream(conn, channel_id, BAD)

        assert sorted(_live_ids(conn, channel_id)) == [GOOD, BAD]
        assert not stream_removed_by_user(conn, channel_id, BAD)
        assert get_user_removed_streams(conn, channel_id) == []
        # Nothing left to undo.
        assert not restore_user_removed_stream(conn, channel_id, BAD)


# ---------------------------------------------------------------------------
# Remove / Undo against Dispatcharr
# ---------------------------------------------------------------------------


def test_remove_detaches_in_dispatcharr_and_records_it(db_factory, seeded):
    _, channel_id = seeded
    cm = _channel_manager([GOOD, BAD])

    exclusion.remove_event_stream(db_factory, cm, channel_id, BAD)

    cm.update_channel.assert_called_once_with(DISP_ID, {"streams": [GOOD]})
    with db_factory() as conn:
        assert _live_ids(conn, channel_id) == [GOOD]
        assert stream_removed_by_user(conn, channel_id, BAD)
        history = conn.execute(
            "SELECT change_type, change_source FROM managed_channel_history "
            "WHERE managed_channel_id = ?",
            (channel_id,),
        ).fetchall()
    assert ("stream_removed", "manual") in [tuple(row) for row in history]


def test_a_refused_detach_stores_nothing(db_factory, seeded):
    """The dashboard and Dispatcharr never disagree about a removal."""
    _, channel_id = seeded
    cm = _channel_manager([GOOD, BAD], accepts=False)

    with pytest.raises(exclusion.DispatcharrUpdateFailed):
        exclusion.remove_event_stream(db_factory, cm, channel_id, BAD)

    with db_factory() as conn:
        assert sorted(_live_ids(conn, channel_id)) == [GOOD, BAD]
        assert not stream_removed_by_user(conn, channel_id, BAD)


def test_an_unreachable_dispatcharr_stores_nothing(db_factory, seeded):
    """Unreachable is not "channel gone"."""
    _, channel_id = seeded
    cm = _channel_manager([GOOD, BAD])
    # No answer, or an answer that is not a 404: inconclusive (#826 shape).
    cm.get_channel_existence.return_value = (None, False)

    with pytest.raises(exclusion.DispatcharrUpdateFailed):
        exclusion.remove_event_stream(db_factory, cm, channel_id, BAD)

    cm.update_channel.assert_not_called()
    with db_factory() as conn:
        assert not stream_removed_by_user(conn, channel_id, BAD)


def test_a_channel_dispatcharr_no_longer_has_is_changed_locally(db_factory, seeded):
    """A confirmed 404 leaves nothing to detach from; the run recreates the
    channel from the stored streams, without the removed one."""
    _, channel_id = seeded
    cm = _channel_manager([GOOD, BAD])
    cm.get_channel_existence.return_value = (None, True)

    exclusion.remove_event_stream(db_factory, cm, channel_id, BAD)

    cm.update_channel.assert_not_called()
    with db_factory() as conn:
        assert stream_removed_by_user(conn, channel_id, BAD)


def test_removing_the_last_stream_leaves_an_empty_channel(db_factory, seeded):
    _, channel_id = seeded
    cm = _channel_manager([GOOD, BAD])
    exclusion.remove_event_stream(db_factory, cm, channel_id, GOOD)
    cm.get_channel_existence.return_value = (_remote([BAD]), False)

    exclusion.remove_event_stream(db_factory, cm, channel_id, BAD)

    assert cm.update_channel.call_args.args == (DISP_ID, {"streams": []})
    with db_factory() as conn:
        assert _live_ids(conn, channel_id) == []
        assert get_managed_channel(conn, channel_id).deleted_at is None


def test_remove_of_a_stream_not_on_the_channel_is_refused(db_factory, seeded):
    _, channel_id = seeded
    with pytest.raises(exclusion.StreamNotOnChannel):
        exclusion.remove_event_stream(db_factory, _channel_manager([GOOD, BAD]), channel_id, 999)
    with pytest.raises(exclusion.StreamNotOnChannel):
        exclusion.restore_event_stream(db_factory, _channel_manager([GOOD, BAD]), channel_id, BAD)


def test_undo_appends_the_stream_without_reordering(db_factory, seeded):
    """The run's ordering pass places it; a live event's first stream is not
    moved by an Undo."""
    _, channel_id = seeded
    cm = _channel_manager([GOOD, BAD])
    exclusion.remove_event_stream(db_factory, cm, channel_id, GOOD)
    cm.get_channel_existence.return_value = (_remote([BAD]), False)
    cm.update_channel.reset_mock()

    exclusion.restore_event_stream(db_factory, cm, channel_id, GOOD)

    cm.update_channel.assert_called_once_with(DISP_ID, {"streams": [BAD, GOOD]})
    with db_factory() as conn:
        assert sorted(_live_ids(conn, channel_id)) == [GOOD, BAD]
        assert not stream_removed_by_user(conn, channel_id, GOOD)


def test_undo_of_a_time_shared_stream_outside_its_slot_pushes_nothing(db_factory):
    """Its window sync attaches it when the slot opens (183.5)."""
    with db_factory() as conn:
        group_id = create_group(conn, name="Linear", leagues=["nfl"])
        channel_id = _channel(conn, group_id)
        _attach(conn, channel_id, GOOD)
        _attach(conn, channel_id, BAD, attach_at=_stamp(120), detach_at=_stamp(300))
        remove_stream_from_channel(conn, channel_id, BAD, reason=USER_REMOVED_REASON)
    cm = _channel_manager([GOOD])

    exclusion.restore_event_stream(db_factory, cm, channel_id, BAD)

    cm.update_channel.assert_not_called()
    with db_factory() as conn:
        assert sorted(_live_ids(conn, channel_id)) == [GOOD, BAD]
        assert get_ordered_stream_ids(conn, channel_id) == [GOOD]


# ---------------------------------------------------------------------------
# Gate 1: the creator's consolidate add
# ---------------------------------------------------------------------------


def _lifecycle(cm):
    sports_service = MagicMock()
    sports_service.get_sport_display_name.return_value = "Football"
    service = ChannelLifecycleService(
        db_factory=MagicMock(),
        sports_service=sports_service,
        channel_manager=cm,
        logo_manager=MagicMock(),
        epg_manager=MagicMock(),
        m3u_manager=MagicMock(),
    )
    return service


def _consolidate(service, conn, channel_id, stream_id):
    return service._handle_existing_channel(
        conn=conn,
        existing=get_managed_channel(conn, channel_id),
        stream={"id": stream_id, "name": f"Feed {stream_id}"},
        event=FakeEvent(),
        effective_mode="consolidate",
        matched_keyword=None,
        group_config={},
        template=None,
    )


def test_the_run_does_not_put_a_removed_stream_back(db_factory, seeded):
    _, channel_id = seeded
    cm = _channel_manager([GOOD])
    service = _lifecycle(cm)
    service._sync_channel_settings = MagicMock(return_value=StreamProcessResult())
    with db_factory() as conn:
        remove_stream_from_channel(conn, channel_id, BAD, reason=USER_REMOVED_REASON)

        result = _consolidate(service, conn, channel_id, BAD)
        service._flush_pending_stream_pushes(conn, result)

        assert _live_ids(conn, channel_id) == [GOOD]
        assert result.existing[0]["action"] == "removed_by_user"
    cm.update_channel.assert_not_called()


def test_the_same_stream_still_attaches_to_another_channel(db_factory, seeded):
    """The removal is per channel, not a rule about the stream."""
    group_id, channel_id = seeded
    cm = _channel_manager([GOOD])
    service = _lifecycle(cm)
    service._sync_channel_settings = MagicMock(return_value=StreamProcessResult())
    with db_factory() as conn:
        other = _channel(conn, group_id, event_id="401872999", disp_id=901)
        remove_stream_from_channel(conn, channel_id, BAD, reason=USER_REMOVED_REASON)

        _consolidate(service, conn, other, BAD)

        assert _live_ids(conn, other) == [BAD]
        assert _live_ids(conn, channel_id) == [GOOD]


def test_after_undo_the_run_treats_the_stream_as_a_member_again(db_factory, seeded):
    _, channel_id = seeded
    cm = _channel_manager([GOOD, BAD])
    service = _lifecycle(cm)
    service._sync_channel_settings = MagicMock(return_value=StreamProcessResult())
    with db_factory() as conn:
        remove_stream_from_channel(conn, channel_id, BAD, reason=USER_REMOVED_REASON)
        restore_user_removed_stream(conn, channel_id, BAD)

        result = _consolidate(service, conn, channel_id, BAD)

        assert result.existing[0]["action"] == "consolidated"
        assert sorted(_live_ids(conn, channel_id)) == [GOOD, BAD]


# ---------------------------------------------------------------------------
# Gate 2: the settings sync's stream drift fix
# ---------------------------------------------------------------------------


def _sync_settings(service, conn, channel_id, stream_id):
    with (
        patch.object(service, "_generate_channel_name", return_value="NFL | PIT/CLE"),
        patch.object(service, "_sync_channel_profiles"),
        patch.object(service, "_sync_channel_logo"),
        patch.object(service, "_sync_stream_profile"),
        patch.object(service._dynamic_resolver, "resolve_channel_group", return_value=None),
    ):
        service._sync_channel_settings(
            conn,
            get_managed_channel(conn, channel_id),
            {"id": stream_id},
            FakeEvent(start_time=datetime.now(UTC)),
            {},
            None,
        )


def _pushed_streams(cm):
    return [
        call.args[1]["streams"]
        for call in cm.update_channel.call_args_list
        if "streams" in call.args[1]
    ]


def test_drift_fix_does_not_push_a_removed_stream_back(db_factory, seeded):
    """A channel made in separate mode is found by its own stream, and the
    settings sync re-adds a stream Dispatcharr lacks."""
    _, channel_id = seeded
    cm = _channel_manager([GOOD])
    service = _lifecycle(cm)
    service._db_factory = db_factory
    with db_factory() as conn:
        remove_stream_from_channel(conn, channel_id, BAD, reason=USER_REMOVED_REASON)
        _sync_settings(service, conn, channel_id, BAD)
    assert _pushed_streams(cm) == []


def test_drift_fix_still_repairs_a_stream_the_user_did_not_remove(db_factory, seeded):
    _, channel_id = seeded
    cm = _channel_manager([GOOD])
    service = _lifecycle(cm)
    service._db_factory = db_factory
    with db_factory() as conn:
        _sync_settings(service, conn, channel_id, BAD)
    assert _pushed_streams(cm) == [[GOOD, BAD]]


# ---------------------------------------------------------------------------
# Gate 3: keyword enforcement
# ---------------------------------------------------------------------------


def test_keyword_enforcement_does_not_move_a_stream_onto_a_channel_it_was_removed_from(
    db_factory,
):
    name = "NFL Game Pass 02: Steelers @ Browns (Prime Vision)"
    with db_factory() as conn:
        conn.execute(
            "INSERT INTO consolidation_exception_keywords (label, match_terms, behavior)"
            " VALUES ('Prime Vision', 'prime vision', 'consolidate')"
        )
        group_id = create_group(conn, name="NFL Game Pass", leagues=["nfl"])
        main = _channel(conn, group_id, disp_id=900)
        vision = _channel(conn, group_id, keyword="Prime Vision", disp_id=901)
        _attach(conn, main, BAD, name, source_group_id=group_id)
        _attach(conn, vision, BAD, name, source_group_id=group_id)
        remove_stream_from_channel(conn, vision, BAD, reason=USER_REMOVED_REASON)

    result = KeywordEnforcer(db_factory=db_factory, channel_manager=None).enforce()

    assert result.moved_count == 1
    with db_factory() as conn:
        # It leaves the channel it does not belong on, and is not put back
        # on the one the user took it off.
        assert _live_ids(conn, main) == []
        assert _live_ids(conn, vision) == []
        assert stream_removed_by_user(conn, vision, BAD)


# ---------------------------------------------------------------------------
# The per-run cleanup: an emptied channel stays, a "no event" stream goes
# ---------------------------------------------------------------------------


def _cleanup_service(db_factory):
    service = ChannelLifecycleService(
        db_factory=db_factory,
        sports_service=MagicMock(),
        channel_manager=MagicMock(),
    )
    service._remove_stream_from_dispatcharr_channel = MagicMock(return_value=True)
    service.delete_managed_channel = MagicMock(return_value=True)
    return service


def _pool(*stream_ids):
    return {sid: {"id": sid, "name": f"Feed {sid}"} for sid in stream_ids}


def _matched(stream_id, event_id=EVENT):
    event = MagicMock()
    event.id = event_id
    return {"stream": {"id": stream_id, "name": f"Feed {stream_id}"}, "event": event}


def test_a_channel_the_user_emptied_is_not_deleted_when_its_other_stream_goes(db_factory, seeded):
    """Deleted, the event would get a new channel the next time the removed
    stream matched, and that channel would not carry the removal."""
    group_id, channel_id = seeded
    with db_factory() as conn:
        remove_stream_from_channel(conn, channel_id, BAD, reason=USER_REMOVED_REASON)
    service = _cleanup_service(db_factory)

    # GOOD has left the M3U and nothing matched this event this run.
    result = service.cleanup_deleted_streams(
        group_id, _pool(BAD, 333), matched_streams=[_matched(333, "another-event")]
    )

    service.delete_managed_channel.assert_not_called()
    assert result.deleted == []
    with db_factory() as conn:
        assert _live_ids(conn, channel_id) == []


def test_a_channel_with_no_streams_left_by_the_user_survives_the_legacy_check(db_factory):
    with db_factory() as conn:
        group_id = create_group(conn, name="NFL Game Pass", leagues=["nfl"])
        channel_id = _channel(conn, group_id, primary_stream_id=BAD)
        _attach(conn, channel_id, BAD, source_group_id=group_id)
        remove_stream_from_channel(conn, channel_id, BAD, reason=USER_REMOVED_REASON)
    service = _cleanup_service(db_factory)

    # Its primary stream has left the M3U as well.
    service.cleanup_deleted_streams(group_id, _pool(GOOD), matched_streams=[_matched(GOOD)])

    service.delete_managed_channel.assert_not_called()


def _skip(db_factory, group_id, stream_id, name):
    StreamMatchCache(db_factory).set_user_correction(
        group_id=group_id,
        stream_id=stream_id,
        stream_name=name,
        event_id=None,
        league=None,
        cached_data={},
    )


def test_a_no_event_correction_detaches_the_stream_it_was_made_on(db_factory, seeded):
    group_id, channel_id = seeded
    _skip(db_factory, group_id, BAD, f"Feed {BAD}")
    service = _cleanup_service(db_factory)

    # The skipped stream no longer matches anything; GOOD still does.
    service.cleanup_deleted_streams(group_id, _pool(GOOD, BAD), matched_streams=[_matched(GOOD)])

    service._remove_stream_from_dispatcharr_channel.assert_called_once_with(DISP_ID, BAD)
    with db_factory() as conn:
        assert _live_ids(conn, channel_id) == [GOOD]
        notes = [
            row[0]
            for row in conn.execute(
                "SELECT notes FROM managed_channel_history WHERE managed_channel_id = ?",
                (channel_id,),
            )
        ]
    assert any("no event" in note for note in notes)


def test_a_no_event_correction_is_not_held_by_a_live_event(db_factory, seeded):
    """The #1174 hold protects a game from a provider's renames, not from the
    user's own decision."""
    group_id, channel_id = seeded
    with db_factory() as conn:
        conn.execute(
            "UPDATE managed_channels SET event_date = ?, event_end_estimate = ? WHERE id = ?",
            (_stamp(-60), _stamp(90), channel_id),
        )
    _skip(db_factory, group_id, BAD, f"Feed {BAD}")
    service = _cleanup_service(db_factory)

    service.cleanup_deleted_streams(
        group_id,
        _pool(GOOD, BAD),
        matched_streams=[_matched(GOOD)],
        event_states={EVENT: "live"},
    )

    with db_factory() as conn:
        assert _live_ids(conn, channel_id) == [GOOD]


def test_a_correction_made_on_another_name_does_not_detach(db_factory, seeded):
    """The matcher keys a skip on the stream's current name; so does this."""
    group_id, channel_id = seeded
    _skip(db_factory, group_id, BAD, "Yesterday's name for this slot")
    service = _cleanup_service(db_factory)

    service.cleanup_deleted_streams(
        group_id, _pool(GOOD, BAD), matched_streams=[_matched(GOOD), _matched(BAD)]
    )

    with db_factory() as conn:
        assert sorted(_live_ids(conn, channel_id)) == [GOOD, BAD]


def test_a_channel_whose_only_stream_is_marked_no_event_is_deleted(db_factory):
    with db_factory() as conn:
        group_id = create_group(conn, name="Live Events", leagues=["nascar-xfinity"])
        channel_id = _channel(conn, group_id)
        _attach(conn, channel_id, BAD, source_group_id=group_id)
    _skip(db_factory, group_id, BAD, f"Feed {BAD}")
    service = _cleanup_service(db_factory)

    service.cleanup_deleted_streams(group_id, _pool(BAD), matched_streams=None, changed_only=True)

    service.delete_managed_channel.assert_called_once()
    assert "no event" in service.delete_managed_channel.call_args.kwargs["reason"]


# ---------------------------------------------------------------------------
# Team channels: same Remove and Undo, scoped to the game
# ---------------------------------------------------------------------------

TEAM = 1
TEAM_DISP_ID = 700


@pytest.fixture
def team(db_factory):
    with db_factory() as conn:
        group_id = create_group(conn, name="NHL", leagues=["nhl"])
        conn.execute(
            "INSERT INTO teams (id, provider_team_id, primary_league, sport, team_name, "
            "channel_id, managed_channel_enabled) "
            "VALUES (?, '25', 'nhl', 'hockey', 'Seattle Kraken', 'kraken.nhl', 1)",
            (TEAM,),
        )
        conn.execute(
            "INSERT INTO managed_team_channels (team_id, dispatcharr_channel_id, "
            "channel_number, sync_status) VALUES (?, ?, 9000, 'ready')",
            (TEAM, TEAM_DISP_ID),
        )
    return group_id


def _membership(group_id, stream_id, event_id="tonight", *, attach=-60, detach=180):
    return {
        "team_id": TEAM,
        "dispatcharr_stream_id": stream_id,
        "event_id": event_id,
        "event_provider": "espn",
        "source_group_id": group_id,
        "stream_name": f"Feed {stream_id}",
        "priority": stream_id,
        "event_start": _stamp(attach + 60),
        "attach_at": _stamp(attach),
        "detach_at": _stamp(detach),
    }


def _team_manager(streams, *, accepts=True):
    cm = MagicMock()
    cm.get_channel_existence.return_value = (_remote(streams, TEAM_DISP_ID), False)
    cm.update_channel.return_value = OperationResult(
        success=accepts, error=None if accepts else "500"
    )
    return cm


def test_team_remove_detaches_and_the_run_does_not_put_it_back(db_factory, team):
    tonight = [_membership(team, GOOD), _membership(team, BAD)]
    with db_factory() as conn:
        reconcile_team_streams(conn, tonight)
    cm = _team_manager([GOOD, BAD])

    exclusion.remove_team_stream(db_factory, cm, TEAM, BAD)

    cm.update_channel.assert_called_once_with(TEAM_DISP_ID, {"streams": [GOOD]})
    with db_factory() as conn:
        # The next run matches both streams again.
        reconcile_team_streams(conn, tonight)
        assert active_stream_ids(conn, TEAM) == [GOOD]
        assert [s["dispatcharr_stream_id"] for s in get_user_removed_team_streams(conn, TEAM)] == [
            BAD
        ]


def test_team_removal_covers_one_game_not_the_stream(db_factory, team):
    """A team channel outlives its games: the same stream is offered again
    for the next one."""
    with db_factory() as conn:
        reconcile_team_streams(conn, [_membership(team, BAD)])
    exclusion.remove_team_stream(db_factory, _team_manager([BAD]), TEAM, BAD)

    with db_factory() as conn:
        reconcile_team_streams(
            conn,
            [_membership(team, BAD), _membership(team, BAD, "tomorrow", attach=-30, detach=200)],
        )
        rows = conn.execute(
            "SELECT event_id FROM managed_team_channel_streams "
            "WHERE team_id = ? AND removed_at IS NULL",
            (TEAM,),
        ).fetchall()
    assert [row[0] for row in rows] == ["tomorrow"]


def test_team_remove_takes_every_membership_of_the_stream_for_the_game(db_factory, team):
    """One row per source and programme slot; a sibling row would keep it on."""
    with db_factory() as conn:
        other_group = create_group(conn, name="NHL backup", leagues=["nhl"])
        reconcile_team_streams(conn, [_membership(team, BAD), _membership(other_group, BAD)])
    cm = _team_manager([BAD])

    exclusion.remove_team_stream(db_factory, cm, TEAM, BAD)

    cm.update_channel.assert_called_once_with(TEAM_DISP_ID, {"streams": []})
    with db_factory() as conn:
        assert active_stream_ids(conn, TEAM) == []


def test_team_undo_restores_the_stream(db_factory, team):
    tonight = [_membership(team, GOOD), _membership(team, BAD)]
    with db_factory() as conn:
        reconcile_team_streams(conn, tonight)
    cm = _team_manager([GOOD, BAD])
    exclusion.remove_team_stream(db_factory, cm, TEAM, BAD)
    cm.get_channel_existence.return_value = (_remote([GOOD], TEAM_DISP_ID), False)
    cm.update_channel.reset_mock()

    exclusion.restore_team_stream(db_factory, cm, TEAM, BAD)

    cm.update_channel.assert_called_once_with(TEAM_DISP_ID, {"streams": [GOOD, BAD]})
    with db_factory() as conn:
        reconcile_team_streams(conn, tonight)
        assert active_stream_ids(conn, TEAM) == [GOOD, BAD]
        assert get_user_removed_team_streams(conn, TEAM) == []


def test_a_refused_team_detach_puts_the_rows_back(db_factory, team):
    with db_factory() as conn:
        reconcile_team_streams(conn, [_membership(team, GOOD), _membership(team, BAD)])

    with pytest.raises(exclusion.DispatcharrUpdateFailed):
        exclusion.remove_team_stream(
            db_factory, _team_manager([GOOD, BAD], accepts=False), TEAM, BAD
        )

    with db_factory() as conn:
        assert active_stream_ids(conn, TEAM) == [GOOD, BAD]
        assert get_user_removed_team_streams(conn, TEAM) == []


def test_a_team_removal_is_kept_until_its_game_is_over(db_factory, team):
    """Removed rows are purged after a week; purged while the game is still
    ahead, the next run would attach the stream again."""
    with db_factory() as conn:
        reconcile_team_streams(
            conn,
            [
                _membership(team, BAD, "ahead", attach=-60, detach=600),
                _membership(team, GOOD, "over", attach=-60, detach=600),
            ],
        )
        conn.execute(
            "UPDATE managed_team_channel_streams SET removed_at = datetime('now', '-30 days'), "
            "remove_reason = ?",
            (USER_REMOVED_REASON,),
        )
        conn.execute(
            "UPDATE managed_team_channel_streams SET detach_at = datetime('now', '-29 days') "
            "WHERE event_id = 'over'"
        )

        reconcile_team_streams(conn, [])

        left = [row[0] for row in conn.execute("SELECT event_id FROM managed_team_channel_streams")]
    assert left == ["ahead"]
