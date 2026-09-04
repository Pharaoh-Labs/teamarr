"""Dispatcharr stream ORDER converges on every generation (#712).

The ordering step used to push only when a local priority *changed*. Priorities
are computed at insert time from the same rules, so a steady-state channel
recomputed to the value it already had, `reordered_count` stayed 0, and Teamarr
never pushed — whatever order Dispatcharr happened to be holding became
permanent. These tests pin the convergence: the intended order is compared
against Dispatcharr's actual order, and any difference is enough to re-push.

No ordering rules are configured here, so the ordering service is skipped and
seeded priorities are left untouched — exactly the steady state where the old
change-gated push went silent.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from teamarr.consumers.generation import _apply_stream_ordering, _run_stream_audit
from teamarr.dispatcharr.types import DispatcharrChannel, OperationResult

D_CHANNEL_ID = 100


def _seed_channel(conn, streams, event_date=None, scheduled_delete_at=None):
    """One managed channel whose streams carry an explicit priority order."""
    conn.execute(
        """INSERT INTO managed_channels
           (id, event_id, event_provider, tvg_id, channel_name,
            channel_number, dispatcharr_channel_id, dispatcharr_uuid,
            event_date, scheduled_delete_at)
           VALUES (1, '123', 'espn', 'teamarr-event-123', 'Test Channel',
                   '5001', ?, 'uuid-100', ?, ?)""",
        (D_CHANNEL_ID, event_date, scheduled_delete_at),
    )
    for priority, stream_id in enumerate(streams):
        conn.execute(
            """INSERT INTO managed_channel_streams
               (managed_channel_id, dispatcharr_stream_id, stream_name, priority)
               VALUES (1, ?, ?, ?)""",
            (stream_id, f"Stream {stream_id}", priority),
        )
    conn.commit()


def _fake_manager(dispatcharr_streams):
    """ChannelManager stand-in holding a given Dispatcharr-side stream order."""
    channel = DispatcharrChannel(
        id=D_CHANNEL_ID,
        uuid="uuid-100",
        name="Test Channel",
        channel_number="5001",
        tvg_id="teamarr-event-123",
        streams=tuple(dispatcharr_streams),
    )
    cm = MagicMock()
    cm.get_channels.return_value = [channel]
    cm.get_channel.return_value = channel
    cm.update_channel.return_value = OperationResult(success=True)
    return cm


def _run(db_factory, cm, manual=False):
    with patch("teamarr.consumers.generation.ChannelManager", return_value=cm):
        return _apply_stream_ordering(db_factory, MagicMock(), MagicMock(), manual=manual)


def _pushed_streams(cm):
    """The stream lists handed to Dispatcharr, in call order."""
    return [
        call.args[1]["streams"]
        for call in cm.update_channel.call_args_list
        if "streams" in call.args[1]
    ]


class TestOrderConvergence:
    def test_repushes_when_dispatcharr_order_differs(self, db_factory, db_conn):
        """No priority changed, but Dispatcharr holds the wrong order → push."""
        _seed_channel(db_conn, [456, 789])
        cm = _fake_manager([789, 456])

        result = _run(db_factory, cm)

        assert _pushed_streams(cm) == [[456, 789]]
        assert result["streams_reordered"] == 0
        assert result["order_drift_synced"] == 1

    def test_no_push_when_order_already_matches(self, db_factory, db_conn):
        """The steady state stays quiet — convergence must not push every run."""
        _seed_channel(db_conn, [456, 789])
        cm = _fake_manager([456, 789])

        result = _run(db_factory, cm)

        assert _pushed_streams(cm) == []
        assert result["order_drift_synced"] == 0

    def test_retries_after_a_failed_push(self, db_factory, db_conn):
        """A rejected push is re-detected next run (#712 closed loop).

        Before this, a failure only logged: the DB was already "correct", so
        `reordered_count` was 0 on every subsequent run and the retry never came.
        """
        _seed_channel(db_conn, [456, 789])
        cm = _fake_manager([789, 456])
        cm.update_channel.return_value = OperationResult(success=False, error="boom")

        _run(db_factory, cm)
        # Dispatcharr still holds the old order, so a second run tries again.
        second = _run(db_factory, cm)

        assert _pushed_streams(cm) == [[456, 789], [456, 789]]
        assert second["order_drift_synced"] == 1

    def test_membership_drift_also_repushes(self, db_factory, db_conn):
        """A stream missing on the Dispatcharr side is drift too."""
        _seed_channel(db_conn, [456, 789])
        cm = _fake_manager([456])

        _run(db_factory, cm)

        assert _pushed_streams(cm) == [[456, 789]]

    def test_unreadable_dispatcharr_order_falls_back_quietly(self, db_factory, db_conn):
        """Convergence is best-effort: a list failure must not fail the run."""
        _seed_channel(db_conn, [456, 789])
        cm = _fake_manager([789, 456])
        cm.get_channels.side_effect = Exception("connection refused")

        result = _run(db_factory, cm)

        assert _pushed_streams(cm) == []
        assert "error" not in result


class TestLivePinInteraction:
    """The #232 pin still owns slot 1 while an event is live."""

    @staticmethod
    def _live_dates():
        now = datetime.now(UTC)
        return (
            (now - timedelta(minutes=30)).isoformat(),
            (now + timedelta(hours=3)).isoformat(),
        )

    def test_pin_holds_dispatcharr_top_stream(self, db_factory, db_conn):
        """The watched stream is Dispatcharr's #1, not the DB's — it stays put."""
        event_date, delete_at = self._live_dates()
        _seed_channel(db_conn, [456, 789], event_date, delete_at)
        cm = _fake_manager([789, 456])

        _run(db_factory, cm)

        # Order differs from the DB, but 789 is what someone is watching, so the
        # push (if any) must not displace it — here it matches, so none is made.
        assert _pushed_streams(cm) == []

    def test_pin_still_converges_the_rest_of_the_list(self, db_factory, db_conn):
        """Below slot 1, priority order is still enforced mid-broadcast."""
        event_date, delete_at = self._live_dates()
        _seed_channel(db_conn, [456, 789, 111], event_date, delete_at)
        cm = _fake_manager([111, 789, 456])

        _run(db_factory, cm)

        assert _pushed_streams(cm) == [[111, 456, 789]]

    def test_manual_run_bypasses_the_pin(self, db_factory, db_conn):
        """A user-triggered run restores rule-truth order (#232 escape hatch)."""
        event_date, delete_at = self._live_dates()
        _seed_channel(db_conn, [456, 789], event_date, delete_at)
        cm = _fake_manager([789, 456])

        _run(db_factory, cm, manual=True)

        assert _pushed_streams(cm) == [[456, 789]]

    def test_order_resumes_once_the_event_ends(self, db_factory, db_conn):
        """The post-event push the pin's contract promises actually happens."""
        now = datetime.now(UTC)
        _seed_channel(
            db_conn,
            [456, 789],
            (now - timedelta(hours=9)).isoformat(),
            (now - timedelta(hours=2)).isoformat(),
        )
        cm = _fake_manager([789, 456])  # left pinned from the broadcast

        _run(db_factory, cm)

        assert _pushed_streams(cm) == [[456, 789]]


class TestStreamAuditSeesOrder:
    """The post-run audit reports order drift instead of declaring success."""

    def _audit_logs(self, db_factory, cm, caplog):
        client = MagicMock()
        client.channels._client = MagicMock()
        with (
            patch("teamarr.consumers.generation.ChannelManager", return_value=cm),
            caplog.at_level("DEBUG", logger="teamarr.consumers.generation"),
        ):
            _run_stream_audit(db_factory, client)
        return caplog.text

    def test_order_only_mismatch_is_reported(self, db_factory, db_conn, caplog):
        _seed_channel(db_conn, [456, 789])
        text = self._audit_logs(db_factory, _fake_manager([789, 456]), caplog)

        assert "ORDER MISMATCH" in text
        assert "All channels match" not in text

    def test_matching_order_reports_success(self, db_factory, db_conn, caplog):
        _seed_channel(db_conn, [456, 789])
        text = self._audit_logs(db_factory, _fake_manager([456, 789]), caplog)

        assert "All channels match" in text

    def test_live_pinned_order_is_not_flagged(self, db_factory, db_conn, caplog):
        """A live channel's reordering is the pin doing its job, not drift."""
        now = datetime.now(UTC)
        _seed_channel(
            db_conn,
            [456, 789],
            (now - timedelta(minutes=30)).isoformat(),
            (now + timedelta(hours=3)).isoformat(),
        )
        text = self._audit_logs(db_factory, _fake_manager([789, 456]), caplog)

        assert "ORDER MISMATCH" not in text
        assert "All channels match" in text

    def test_membership_mismatch_still_reported(self, db_factory, db_conn, caplog):
        _seed_channel(db_conn, [456, 789])
        text = self._audit_logs(db_factory, _fake_manager([456]), caplog)

        assert "MISMATCH" in text
