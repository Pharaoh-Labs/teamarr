"""Postponed events can be kept off event channels (#948).

Event channels were created for postponed events with only a "Postponed:"
label to tell them apart. `channel_create_postponed` (default on) turns that
off: a matched postponed event is excluded at the lifecycle gate with its own
reason, and a channel created before the postponement is deleted.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from teamarr.consumers.lifecycle import get_lifecycle_settings
from teamarr.consumers.lifecycle.service import ChannelLifecycleService
from teamarr.consumers.lifecycle.timing import ChannelLifecycleManager
from teamarr.consumers.lifecycle.types import StreamProcessResult
from teamarr.consumers.matching.result import EXCLUDED_DISPLAY, ExcludedReason
from teamarr.core import EventStatus
from teamarr.database.channels import create_managed_channel, get_managed_channel
from teamarr.database.groups import create_group
from teamarr.database.settings import update_lifecycle_settings
from tests.fakes import make_event


def _event(state):
    # Starts in an hour: inside the same-day window, not final, not past.
    return make_event(
        start_time=datetime.now(UTC) + timedelta(hours=1), status=EventStatus(state=state)
    )


class TestTimingGate:
    def test_postponed_is_excluded_when_off(self):
        manager = ChannelLifecycleManager(create_postponed=False)
        verdict = manager.categorize_event_timing(_event("postponed"))
        assert verdict is ExcludedReason.EVENT_POSTPONED

    def test_postponed_is_kept_by_default(self):
        manager = ChannelLifecycleManager()
        assert manager.categorize_event_timing(_event("postponed")) is not (
            ExcludedReason.EVENT_POSTPONED
        )

    def test_other_events_are_unaffected_when_off(self):
        manager = ChannelLifecycleManager(create_postponed=False)
        assert manager.categorize_event_timing(_event("pre")) is not ExcludedReason.EVENT_POSTPONED

    def test_reason_wins_over_the_window(self):
        """A postponed game keeps its original start; say why, not 'already ended'."""
        manager = ChannelLifecycleManager(create_postponed=False)
        past = make_event(
            start_time=datetime.now(UTC) - timedelta(days=3), status=EventStatus(state="postponed")
        )
        assert manager.categorize_event_timing(past) is ExcludedReason.EVENT_POSTPONED

    def test_reason_has_display_text(self):
        assert EXCLUDED_DISPLAY[ExcludedReason.EVENT_POSTPONED] == "Event is postponed"


class TestSetting:
    def test_defaults_on(self, db_conn):
        assert get_lifecycle_settings(db_conn)["create_postponed"] is True

    def test_round_trips(self, db_conn):
        update_lifecycle_settings(db_conn, channel_create_postponed=False)
        db_conn.commit()
        assert get_lifecycle_settings(db_conn)["create_postponed"] is False


class TestExistingChannels:
    def test_every_channel_of_the_event_is_deleted(self, db_factory):
        with db_factory() as conn:
            g1 = create_group(conn, name="A", leagues=["mlb"])
            g2 = create_group(conn, name="B", leagues=["mlb"])
            ids = [
                create_managed_channel(
                    conn=conn,
                    event_epg_group_id=group,
                    event_id=event_id,
                    event_provider="espn",
                    tvg_id=f"tvg-{event_id}-{keyword}",
                    channel_name=f"ch-{event_id}-{keyword}",
                    exception_keyword=keyword,
                )
                for group, event_id, keyword in (
                    (g1, "401", None),
                    (g2, "401", "4K"),
                    (g1, "402", None),
                )
            ]
            conn.commit()

        service = ChannelLifecycleService(
            db_factory=db_factory,
            sports_service=MagicMock(),
            channel_manager=None,
            logo_manager=None,
            epg_manager=None,
        )
        result = StreamProcessResult()
        with db_factory() as conn:
            service._delete_postponed_event_channels(conn, "401", "espn", result)
            conn.commit()

        assert len(result.deleted) == 2
        with db_factory() as conn:
            main, keyword, other = (get_managed_channel(conn, i) for i in ids)
        assert main.deleted_at and keyword.deleted_at
        assert other.deleted_at is None
