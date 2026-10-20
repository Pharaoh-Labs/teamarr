"""Consolidate-add phantom purge validates against the catalog (#1097).

A stream in our DB but absent from the channel's Dispatcharr stream list used
to be purged as a phantom on the spot. A time-windowed EPG channel-source
stream whose window has just opened is exactly that in the first run after the
window opens — the ordering phase's window sync has not pushed it yet — and on
a real install every purge over eight days was one of these (444 removals, 22
channels, 0 real phantoms). The purge now holds windowed rows back, asks the
stream catalog about the rest, and removes only ids Dispatcharr does not know.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from teamarr.consumers.lifecycle.service import ChannelLifecycleService
from teamarr.consumers.lifecycle.types import StreamProcessResult
from teamarr.database.channels import (
    add_stream_to_channel,
    get_channel_streams,
    get_managed_channel,
)
from teamarr.dispatcharr.types import DispatcharrChannel, OperationResult
from tests.fakes import FakeEvent

ON_CHANNEL = 10  # full-life, already on the Dispatcharr channel
WINDOWED = 20  # EPG window opened minutes ago, window sync has not pushed it yet
UNSYNCED = 40  # full-life, missing from the channel list for whatever reason
NEW = 30  # the stream being consolidated onto the channel this run


def _utc(delta_minutes: int) -> str:
    return (datetime.now(UTC) + timedelta(minutes=delta_minutes)).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture
def channel(db_conn):
    db_conn.execute(
        "INSERT INTO managed_channels (event_id, event_provider, tvg_id, channel_name, "
        "dispatcharr_channel_id) VALUES ('123', 'espn', 'teamarr-event-123', 'BUF @ LV', 100)"
    )
    channel_id = db_conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    add_stream_to_channel(db_conn, channel_id, ON_CHANNEL, "Sky Main Event", priority=1)
    db_conn.commit()
    return get_managed_channel(db_conn, channel_id)


def _service(known: set[int] | None | object = None, *, m3u: bool = True):
    cm = MagicMock()
    cm.get_channel_existence.return_value = (
        DispatcharrChannel(
            id=100,
            uuid="uuid-100",
            name="BUF @ LV",
            channel_number="5001",
            tvg_id="teamarr-event-123",
            channel_group_id=None,
            logo_id=None,
            logo_url=None,
            streams=(ON_CHANNEL,),
            stream_profile_id=None,
        ),
        False,
    )
    cm.update_channel.return_value = OperationResult(success=True)
    m3u_manager = MagicMock() if m3u else None
    if m3u_manager is not None:
        m3u_manager.known_stream_ids.return_value = known
    sports_service = MagicMock()
    sports_service.get_sport_display_name.return_value = "Football"
    service = ChannelLifecycleService(
        db_factory=MagicMock(),
        sports_service=sports_service,
        channel_manager=cm,
        logo_manager=MagicMock(),
        epg_manager=MagicMock(),
        m3u_manager=m3u_manager,
    )
    return service, cm, m3u_manager


def _consolidate(service, conn, channel):
    with patch.object(service, "_sync_channel_settings", return_value=StreamProcessResult()):
        return service._handle_existing_channel(
            conn=conn,
            existing=channel,
            stream={"id": NEW, "name": "Sky Sports NFL"},
            event=FakeEvent(),
            effective_mode="consolidate",
            matched_keyword=None,
            group_config={},
            template=None,
        )


def _pushed_streams(cm) -> list[int]:
    (_cid, data), _kw = cm.update_channel.call_args
    return list(data["streams"])


def _active_ids(conn, channel_id) -> set[int]:
    return {s.dispatcharr_stream_id for s in get_channel_streams(conn, channel_id)}


def _removed(conn, channel_id) -> dict[int, str]:
    rows = conn.execute(
        "SELECT dispatcharr_stream_id, remove_reason FROM managed_channel_streams "
        "WHERE managed_channel_id = ? AND removed_at IS NOT NULL",
        (channel_id,),
    ).fetchall()
    return {r[0]: r[1] for r in rows}


def _history_notes(conn, channel_id) -> list[str]:
    rows = conn.execute(
        "SELECT notes FROM managed_channel_history WHERE managed_channel_id = ? "
        "AND change_type = 'stream_removed'",
        (channel_id,),
    ).fetchall()
    return [r[0] for r in rows]


def test_windowed_stream_pending_window_sync_is_not_a_phantom(db_conn, channel):
    """The #1097 case: in-window EPG stream, first run after the window opened."""
    add_stream_to_channel(
        db_conn,
        channel.id,
        WINDOWED,
        "Sky Sports NFL",
        priority=2,
        attach_at=_utc(-5),
        detach_at=_utc(+180),
    )
    service, cm, m3u = _service(known=set())

    result = _consolidate(service, db_conn, channel)

    assert result is not None
    assert _active_ids(db_conn, channel.id) == {ON_CHANNEL, WINDOWED, NEW}
    assert _removed(db_conn, channel.id) == {}
    assert _history_notes(db_conn, channel.id) == []
    # Nothing left to ask the catalog about, and the push carries the window.
    m3u.known_stream_ids.assert_not_called()
    assert set(_pushed_streams(cm)) == {ON_CHANNEL, WINDOWED, NEW}


def test_stream_unknown_to_the_catalog_is_purged_with_history(db_conn, channel):
    add_stream_to_channel(db_conn, channel.id, UNSYNCED, "Gone after re-import", priority=2)
    service, cm, m3u = _service(known=set())

    _consolidate(service, db_conn, channel)

    assert _active_ids(db_conn, channel.id) == {ON_CHANNEL, NEW}
    assert _removed(db_conn, channel.id) == {UNSYNCED: "phantom: not in Dispatcharr"}
    assert _history_notes(db_conn, channel.id) == [
        f"Stream {UNSYNCED} purged: no longer exists in Dispatcharr"
    ]
    m3u.known_stream_ids.assert_called_once_with([UNSYNCED])
    assert UNSYNCED not in _pushed_streams(cm)


def test_stream_the_catalog_knows_is_kept_and_re_pushed(db_conn, channel):
    add_stream_to_channel(db_conn, channel.id, UNSYNCED, "Dropped by someone", priority=2)
    service, cm, _m3u = _service(known={UNSYNCED})

    _consolidate(service, db_conn, channel)

    assert _active_ids(db_conn, channel.id) == {ON_CHANNEL, UNSYNCED, NEW}
    assert _removed(db_conn, channel.id) == {}
    assert UNSYNCED in _pushed_streams(cm)


def test_failed_catalog_lookup_purges_nothing(db_conn, channel):
    add_stream_to_channel(db_conn, channel.id, UNSYNCED, "Unverifiable", priority=2)
    service, cm, _m3u = _service(known=None)

    _consolidate(service, db_conn, channel)

    assert _active_ids(db_conn, channel.id) == {ON_CHANNEL, UNSYNCED, NEW}
    assert _removed(db_conn, channel.id) == {}
    assert UNSYNCED in _pushed_streams(cm)


def test_without_a_catalog_nothing_is_purged(db_conn, channel):
    add_stream_to_channel(db_conn, channel.id, UNSYNCED, "Unverifiable", priority=2)
    service, _cm, _m3u = _service(m3u=False)

    _consolidate(service, db_conn, channel)

    assert _active_ids(db_conn, channel.id) == {ON_CHANNEL, UNSYNCED, NEW}
    assert _removed(db_conn, channel.id) == {}


def test_streams_already_on_the_channel_are_never_asked_about(db_conn, channel):
    service, _cm, m3u = _service(known=set())

    _consolidate(service, db_conn, channel)

    m3u.known_stream_ids.assert_not_called()
    assert _active_ids(db_conn, channel.id) == {ON_CHANNEL, NEW}
