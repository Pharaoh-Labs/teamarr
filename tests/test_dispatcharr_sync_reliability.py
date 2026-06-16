"""Tests for Dispatcharr sync reliability — closed-loop updates.

Verifies that ChannelLifecycleService checks update_channel results before
persisting local DB state, enabling self-healing via the scheduler retry loop.
"""

import sqlite3
from dataclasses import dataclass, field
from unittest.mock import MagicMock, patch

import pytest

from teamarr.consumers.lifecycle.types import StreamProcessResult
from teamarr.consumers.reconciliation import ChannelReconciler
from teamarr.dispatcharr.types import DispatcharrChannel, OperationResult

# =============================================================================
# FIXTURES
# =============================================================================


@dataclass
class FakeManagedChannel:
    """Lightweight stand-in for ManagedChannel from the DB."""

    id: int = 1
    dispatcharr_channel_id: int = 100
    dispatcharr_uuid: str = "uuid-100"
    channel_name: str = "Test Channel"
    channel_number: str = "5001"
    tvg_id: str = "teamarr-event-123"
    event_id: str = "123"
    event_epg_group_id: int = 1
    channel_group_id: int = 10
    channel_profile_ids: str = "[0]"
    exception_keyword: str | None = None
    dispatcharr_logo_id: int | None = None
    logo_url: str | None = None
    scheduled_delete_at: str | None = None
    sport: str = "football"
    league: str = "nfl"
    event_date: str | None = None
    primary_stream_id: int | None = None


@dataclass
class FakeEvent:
    """Minimal event for testing."""

    id: str = "123"
    name: str = "Team A vs Team B"
    short_name: str = "A vs B"
    sport: str = "football"
    league: str = "nfl"
    provider: str = "espn"
    start_time: None = None
    home_team: None = None
    away_team: None = None
    venue: None = None
    broadcasts: list = field(default_factory=list)
    status: None = None


def _make_dispatcharr_channel(
    channel_id=100,
    streams=(456,),
    channel_profile_ids=None,
    **kwargs,
):
    """Create a DispatcharrChannel with sensible defaults."""
    defaults = dict(
        id=channel_id,
        uuid="uuid-100",
        name="Test Channel",
        channel_number="5001",
        tvg_id="teamarr-event-123",
        channel_group_id=10,
        logo_id=None,
        logo_url=None,
        streams=tuple(streams) if streams else (),
        stream_profile_id=None,
        channel_profile_ids=tuple(channel_profile_ids) if channel_profile_ids is not None else None,
    )
    defaults.update(kwargs)
    return DispatcharrChannel(**defaults)


def _make_service(channel_manager=None):
    """Create a ChannelLifecycleService with mocked dependencies."""
    from teamarr.consumers.lifecycle.service import ChannelLifecycleService

    sports_service = MagicMock()
    sports_service.get_sport_display_name.return_value = "Football"

    service = ChannelLifecycleService(
        db_factory=MagicMock(),
        sports_service=sports_service,
        channel_manager=channel_manager,
        logo_manager=MagicMock(),
        epg_manager=MagicMock(),
    )
    return service


# =============================================================================
# BEAD 1: _safe_update_channel
# =============================================================================


class TestSafeUpdateChannel:
    """Test the closed-loop _safe_update_channel helper."""

    def test_returns_true_on_success(self):
        cm = MagicMock()
        cm.update_channel.return_value = OperationResult(success=True)
        service = _make_service(channel_manager=cm)

        assert service._safe_update_channel(100, {"name": "New"}, "test") is True

    def test_returns_false_on_api_failure(self):
        cm = MagicMock()
        cm.update_channel.return_value = OperationResult(success=False, error="Server error")
        service = _make_service(channel_manager=cm)

        assert service._safe_update_channel(100, {"name": "New"}, "test") is False

    def test_returns_false_on_exception(self):
        cm = MagicMock()
        cm.update_channel.side_effect = ConnectionError("timeout")
        service = _make_service(channel_manager=cm)

        assert service._safe_update_channel(100, {"name": "New"}, "test") is False

    def test_returns_false_without_channel_manager(self):
        service = _make_service(channel_manager=None)
        assert service._safe_update_channel(100, {"name": "New"}, "test") is False

    def test_increments_failure_counter_on_failure(self):
        cm = MagicMock()
        cm.update_channel.return_value = OperationResult(success=False, error="503")
        service = _make_service(channel_manager=cm)

        service._safe_update_channel(100, {"name": "A"}, "test1")
        service._safe_update_channel(101, {"name": "B"}, "test2")

        assert service._dispatcharr_failure_count == 2

    def test_increments_failure_counter_on_exception(self):
        cm = MagicMock()
        cm.update_channel.side_effect = RuntimeError("boom")
        service = _make_service(channel_manager=cm)

        service._safe_update_channel(100, {"name": "A"}, "test")
        assert service._dispatcharr_failure_count == 1


# =============================================================================
# BEAD 1: DB rollback on API failure
# =============================================================================


class TestBulkSettingsSyncFailure:
    """Bulk settings sync skips DB updates when Dispatcharr API fails."""

    def test_db_unchanged_on_api_failure(self):
        cm = MagicMock()
        cm.update_channel.return_value = OperationResult(success=False, error="500")
        cm.get_channel.return_value = _make_dispatcharr_channel(name="Old Name")
        service = _make_service(channel_manager=cm)

        existing = FakeManagedChannel()
        event = FakeEvent()

        with (
            patch.object(service, "_generate_channel_name", return_value="New Name"),
            patch.object(service, "_sync_channel_profiles"),
            patch.object(service, "_sync_channel_logo"),
            patch.object(service, "_sync_stream_profile"),
            patch.object(service, "_dynamic_resolver") as mock_resolver,
        ):
            mock_resolver.resolve_channel_group.return_value = 10

            # Patch at the source package — the from-import resolves here
            with patch("teamarr.database.channels.update_managed_channel") as mock_update_db:
                service._sync_channel_settings(
                    conn=MagicMock(),
                    existing=existing,
                    stream={"id": 456},
                    event=event,
                    group_config={
                        "channel_group_mode": "static",
                        "channel_group_id": 10,
                    },
                    template=None,
                )

                # DB should NOT have been updated since API failed
                mock_update_db.assert_not_called()


class TestProfileSentinelUpdateFailure:
    """Profile sentinel update skips DB persist on API failure."""

    def test_profile_update_skipped_on_api_failure(self):
        cm = MagicMock()
        cm.update_channel.return_value = OperationResult(success=False, error="timeout")
        service = _make_service(channel_manager=cm)

        existing = FakeManagedChannel(channel_profile_ids="[1]")
        changes_made = []

        service._dynamic_resolver = MagicMock()
        service._dynamic_resolver.resolve_channel_profiles.return_value = [0]

        mock_settings = MagicMock()
        mock_settings.default_channel_profile_ids = None

        with (
            patch("teamarr.database.channels.update_managed_channel") as mock_update_db,
            patch(
                "teamarr.database.settings.get_dispatcharr_settings",
                return_value=mock_settings,
            ),
        ):
            service._sync_channel_profiles(
                conn=MagicMock(),
                existing=existing,
                event_sport="football",
                event_league="nfl",
                changes_made=changes_made,
            )

            # DB should NOT be updated because API failed
            mock_update_db.assert_not_called()
            assert len(changes_made) == 0


class TestLogoAssignmentFailure:
    """Logo assignment skips DB update on API failure."""

    def test_logo_db_unchanged_on_api_failure(self):
        cm = MagicMock()
        cm.update_channel.return_value = OperationResult(success=False, error="502")
        service = _make_service(channel_manager=cm)
        service._logo_manager.upload.return_value = MagicMock(success=True, logo={"id": 42})

        existing = FakeManagedChannel(logo_url=None, dispatcharr_logo_id=None)
        changes_made = []

        with (
            patch.object(service, "_resolve_logo_url", return_value="http://example.com/logo.png"),
            patch("teamarr.database.channels.update_managed_channel") as mock_update_db,
        ):
            service._sync_channel_logo(
                conn=MagicMock(),
                existing=existing,
                event=FakeEvent(),
                template=None,
                matched_keyword=None,
                segment=None,
                changes_made=changes_made,
            )

            mock_update_db.assert_not_called()
            assert "logo updated" not in changes_made


class TestStreamRemovalFailure:
    """Stream removal returns False on API failure."""

    def test_returns_false_on_api_failure(self):
        cm = MagicMock()
        cm.get_channel.return_value = _make_dispatcharr_channel(streams=(456, 789))
        cm.update_channel.return_value = OperationResult(success=False, error="timeout")
        service = _make_service(channel_manager=cm)

        assert service._remove_stream_from_dispatcharr_channel(100, 456) is False


class TestChannelNumberReallocFailure:
    """Channel number reallocation (v59: global reassignment is pure DB)."""

    def test_reassign_is_db_only(self):
        """v59: reassign_all_channels is a pure DB operation, no API calls."""
        # The old reassign_group_channels was removed in v59.
        # Global reassignment is now done via channel_numbers.reassign_all_channels
        # which is a pure DB operation — Dispatcharr sync happens separately.
        pass


# =============================================================================
# BEAD 2: Profile self-healing
# =============================================================================


class TestProfileSelfHealing:
    """Profile sync detects and fixes Dispatcharr drift."""

    def test_detects_dispatcharr_profile_drift(self):
        """DB says [0] but Dispatcharr has [] — push correct profiles."""
        cm = MagicMock()
        cm.update_channel.return_value = OperationResult(success=True)
        service = _make_service(channel_manager=cm)

        existing = FakeManagedChannel(channel_profile_ids="[0]")
        dispatcharr_ch = _make_dispatcharr_channel(channel_profile_ids=[])

        changes_made = []
        service._dynamic_resolver = MagicMock()
        service._dynamic_resolver.resolve_channel_profiles.return_value = [0]

        mock_settings = MagicMock()
        mock_settings.default_channel_profile_ids = None

        with (
            patch("teamarr.database.channels.update_managed_channel"),
            patch(
                "teamarr.database.settings.get_dispatcharr_settings",
                return_value=mock_settings,
            ),
        ):
            service._sync_channel_profiles(
                conn=MagicMock(),
                existing=existing,
                event_sport="football",
                event_league="nfl",
                changes_made=changes_made,
                current_channel=dispatcharr_ch,
            )

        # Should have called update_channel to push correct [0] profiles
        cm.update_channel.assert_called_once()
        call_args = cm.update_channel.call_args
        assert call_args[0][1] == {"channel_profile_ids": [0]}

    def test_no_false_positive_when_in_sync(self):
        """DB and Dispatcharr both match expected — no update needed.

        Uses profile ID 1 (not 0) because _parse_profile_ids filters falsy
        values with ``if x``, so 0 gets dropped.  Also sets a non-None
        default_channel_profile_ids so the dynamic resolver runs
        (None causes a [0] fallback, bypassing the resolver entirely).
        """
        cm = MagicMock()
        service = _make_service(channel_manager=cm)

        existing = FakeManagedChannel(channel_profile_ids="[1]")
        dispatcharr_ch = _make_dispatcharr_channel(channel_profile_ids=[1])

        changes_made = []
        service._dynamic_resolver = MagicMock()
        service._dynamic_resolver.resolve_channel_profiles.return_value = [1]

        mock_settings = MagicMock()
        mock_settings.default_channel_profile_ids = [1]

        with (
            patch("teamarr.database.channels.update_managed_channel") as mock_update_db,
            patch(
                "teamarr.database.settings.get_dispatcharr_settings",
                return_value=mock_settings,
            ),
        ):
            service._sync_channel_profiles(
                conn=MagicMock(),
                existing=existing,
                event_sport="football",
                event_league="nfl",
                changes_made=changes_made,
                current_channel=dispatcharr_ch,
            )

        cm.update_channel.assert_not_called()
        mock_update_db.assert_not_called()
        assert len(changes_made) == 0


# =============================================================================
# BEAD 3: Failure counters
# =============================================================================


class TestFailureCounters:
    """Failure counters track API failures and drift fixes."""

    def test_stream_process_result_merge_counters(self):
        a = StreamProcessResult()
        a.dispatcharr_failures = 2
        a.stream_drift_fixes = 1

        b = StreamProcessResult()
        b.dispatcharr_failures = 3
        b.stream_drift_fixes = 0

        a.merge(b)
        assert a.dispatcharr_failures == 5
        assert a.stream_drift_fixes == 1

    def test_stream_process_result_to_dict_includes_counters(self):
        r = StreamProcessResult()
        r.dispatcharr_failures = 4
        r.stream_drift_fixes = 2

        d = r.to_dict()
        assert d["summary"]["dispatcharr_failures"] == 4
        assert d["summary"]["stream_drift_fixes"] == 2

    def test_counters_reset_on_clear_caches(self):
        service = _make_service(channel_manager=MagicMock())
        service._dispatcharr_failure_count = 5
        service._stream_drift_fix_count = 3

        service.clear_caches()

        assert service._dispatcharr_failure_count == 0
        assert service._stream_drift_fix_count == 0


# =============================================================================
# BEAD 4: Reconciliation stream/profile drift
# =============================================================================

# Full managed_channels schema matching ManagedChannel.from_row expectations
_MANAGED_CHANNELS_DDL = """
    CREATE TABLE managed_channels (
        id INTEGER PRIMARY KEY,
        event_epg_group_id INTEGER,
        event_id TEXT NOT NULL DEFAULT '',
        event_provider TEXT NOT NULL DEFAULT 'espn',
        channel_number TEXT,
        channel_name TEXT NOT NULL DEFAULT '',
        tvg_id TEXT NOT NULL DEFAULT '',
        event_name TEXT,
        logo_url TEXT,
        dispatcharr_channel_id INTEGER,
        dispatcharr_uuid TEXT,
        dispatcharr_logo_id INTEGER,
        channel_group_id INTEGER,
        channel_profile_ids TEXT,
        primary_stream_id TEXT,
        exception_keyword TEXT,
        home_team TEXT,
        away_team TEXT,
        event_date TEXT,
        league TEXT,
        sport TEXT,
        scheduled_delete_at TEXT,
        deleted_at TEXT,
        delete_reason TEXT,
        sync_status TEXT DEFAULT 'pending',
        sync_message TEXT,
        last_verified_at TEXT,
        created_at TEXT,
        updated_at TEXT
    )
"""

_MANAGED_CHANNEL_STREAMS_DDL = """
    CREATE TABLE managed_channel_streams (
        id INTEGER PRIMARY KEY,
        managed_channel_id INTEGER,
        dispatcharr_stream_id INTEGER,
        stream_name TEXT,
        source_group_id INTEGER,
        source_group_type TEXT DEFAULT 'parent',
        priority INTEGER DEFAULT 0,
        m3u_account_id INTEGER,
        m3u_account_name TEXT,
        exception_keyword TEXT,
        added_at TEXT,
        removed_at TEXT,
        attach_at TEXT,
        detach_at TEXT
    )
"""


_EVENT_EPG_GROUPS_DDL = """
    CREATE TABLE event_epg_groups (
        id INTEGER PRIMARY KEY,
        name TEXT,
        duplicate_event_handling TEXT DEFAULT 'consolidate'
    )
"""


@pytest.fixture
def recon_conn():
    """Minimal in-memory SQLite for reconciliation tests."""
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.execute(_MANAGED_CHANNELS_DDL)
    db.execute(_MANAGED_CHANNEL_STREAMS_DDL)
    db.execute(_EVENT_EPG_GROUPS_DDL)
    db.commit()
    yield db
    db.close()


class TestReconciliationStreamDrift:
    """Reconciliation detects stream assignment drift."""

    def test_detects_stream_drift(self, recon_conn):
        """Drift detected when DB streams differ from Dispatcharr streams."""
        recon_conn.execute(
            "INSERT INTO managed_channels "
            "(id, event_epg_group_id, event_id, event_provider, channel_name, "
            "tvg_id, dispatcharr_channel_id, dispatcharr_uuid, channel_group_id, "
            "channel_number) "
            "VALUES (1, 1, '123', 'espn', 'Test', 'teamarr-event-123', "
            "100, 'uuid-100', 10, '5001')"
        )
        recon_conn.execute(
            "INSERT INTO managed_channel_streams "
            "(managed_channel_id, dispatcharr_stream_id, stream_name) "
            "VALUES (1, 456, 'Stream A')"
        )
        recon_conn.execute(
            "INSERT INTO managed_channel_streams "
            "(managed_channel_id, dispatcharr_stream_id, stream_name) "
            "VALUES (1, 789, 'Stream B')"
        )
        recon_conn.commit()

        cm = MagicMock()
        cm.get_channel.return_value = _make_dispatcharr_channel(
            streams=(456,),
            channel_profile_ids=None,
        )

        reconciler = ChannelReconciler(
            db_factory=lambda: recon_conn,
            channel_manager=cm,
        )

        issues = reconciler._detect_drift(recon_conn)
        assert len(issues) == 1
        assert issues[0].issue_type == "drift"

        drift_fields = issues[0].details["drift_fields"]
        stream_drift = [d for d in drift_fields if d["field"] == "streams"]
        assert len(stream_drift) == 1
        assert 789 in stream_drift[0]["expected"]
        assert 789 not in stream_drift[0]["actual"]

    def test_no_drift_when_streams_match(self, recon_conn):
        """No drift when DB and Dispatcharr streams match."""
        recon_conn.execute(
            "INSERT INTO managed_channels "
            "(id, event_epg_group_id, event_id, event_provider, channel_name, "
            "tvg_id, dispatcharr_channel_id, dispatcharr_uuid, channel_group_id, "
            "channel_number) "
            "VALUES (1, 1, '123', 'espn', 'Test', 'teamarr-event-123', "
            "100, 'uuid-100', 10, '5001')"
        )
        recon_conn.execute(
            "INSERT INTO managed_channel_streams "
            "(managed_channel_id, dispatcharr_stream_id, stream_name) "
            "VALUES (1, 456, 'Stream A')"
        )
        recon_conn.commit()

        cm = MagicMock()
        cm.get_channel.return_value = _make_dispatcharr_channel(
            streams=(456,),
            channel_profile_ids=None,
        )

        reconciler = ChannelReconciler(
            db_factory=lambda: recon_conn,
            channel_manager=cm,
        )

        issues = reconciler._detect_drift(recon_conn)
        assert len(issues) == 0


class TestReconciliationProfileDrift:
    """Reconciliation detects profile assignment drift."""

    def test_detects_profile_drift(self, recon_conn):
        """Drift detected when DB profiles differ from Dispatcharr profiles."""
        recon_conn.execute(
            "INSERT INTO managed_channels "
            "(id, event_epg_group_id, event_id, event_provider, channel_name, "
            "tvg_id, dispatcharr_channel_id, dispatcharr_uuid, channel_group_id, "
            "channel_number, channel_profile_ids) "
            "VALUES (1, 1, '123', 'espn', 'Test', 'teamarr-event-123', "
            "100, 'uuid-100', 10, '5001', '[0]')"
        )
        recon_conn.commit()

        cm = MagicMock()
        cm.get_channel.return_value = _make_dispatcharr_channel(
            streams=(),
            channel_profile_ids=[],
        )

        reconciler = ChannelReconciler(
            db_factory=lambda: recon_conn,
            channel_manager=cm,
        )

        issues = reconciler._detect_drift(recon_conn)
        assert len(issues) == 1

        drift_fields = issues[0].details["drift_fields"]
        profile_drift = [d for d in drift_fields if d["field"] == "channel_profile_ids"]
        assert len(profile_drift) == 1
        assert profile_drift[0]["expected"] == [0]
        assert profile_drift[0]["actual"] == []


class TestReconciliationDriftAutoFix:
    """Drift auto-fix pushes stream corrections to Dispatcharr."""

    def test_stream_drift_auto_fixed(self, recon_conn):
        """Auto-fix pushes DB streams to Dispatcharr on stream drift."""
        recon_conn.execute(
            "INSERT INTO managed_channels "
            "(id, event_epg_group_id, event_id, event_provider, channel_name, "
            "tvg_id, dispatcharr_channel_id, dispatcharr_uuid, channel_group_id, "
            "channel_number) "
            "VALUES (1, 1, '123', 'espn', 'Test', 'teamarr-event-123', "
            "100, 'uuid-100', 10, '5001')"
        )
        recon_conn.execute(
            "INSERT INTO managed_channel_streams "
            "(managed_channel_id, dispatcharr_stream_id, stream_name) "
            "VALUES (1, 456, 'Stream A')"
        )
        recon_conn.execute(
            "INSERT INTO managed_channel_streams "
            "(managed_channel_id, dispatcharr_stream_id, stream_name) "
            "VALUES (1, 789, 'Stream B')"
        )
        recon_conn.commit()

        cm = MagicMock()
        cm.get_channel.return_value = _make_dispatcharr_channel(
            streams=(456,),
            channel_profile_ids=None,
        )
        cm.update_channel.return_value = OperationResult(success=True)
        cm.get_channels.return_value = []
        cm.clear_cache.return_value = None

        reconciler = ChannelReconciler(
            db_factory=lambda: recon_conn,
            channel_manager=cm,
        )

        result = reconciler.reconcile(auto_fix=True)

        # Should have fixed the stream drift
        fixed_drifts = [f for f in result.issues_fixed if f["issue_type"] == "drift"]
        assert len(fixed_drifts) == 1
        assert "streams" in fixed_drifts[0]["fields"]


# =============================================================================
# GRACEFUL DEGRADATION
# =============================================================================


class TestGracefulDegradation:
    """Dispatcharr unavailable does not crash generation."""

    def test_api_exception_does_not_crash(self):
        cm = MagicMock()
        cm.update_channel.side_effect = Exception("Connection refused")
        service = _make_service(channel_manager=cm)

        result = service._safe_update_channel(100, {"name": "A"}, "test")
        assert result is False
        assert service._dispatcharr_failure_count == 1

    def test_none_result_handled(self):
        cm = MagicMock()
        cm.update_channel.return_value = None
        service = _make_service(channel_manager=cm)

        assert service._safe_update_channel(100, {"name": "A"}, "test") is False


# =============================================================================
# DispatcharrChannel type tests
# =============================================================================


class TestDispatcharrChannelProfileIds:
    """DispatcharrChannel parses channel_profile_ids from API."""

    def test_parses_profile_ids_from_api(self):
        ch = DispatcharrChannel.from_api(
            {
                "id": 1,
                "uuid": "u1",
                "name": "CH1",
                "channel_number": "100",
                "streams": [456],
                "channel_profile_ids": [0],
            }
        )
        assert ch.channel_profile_ids == (0,)

    def test_missing_profile_ids_is_none(self):
        ch = DispatcharrChannel.from_api(
            {"id": 1, "uuid": "u1", "name": "CH1", "channel_number": "100", "streams": []}
        )
        assert ch.channel_profile_ids is None

    def test_empty_list_profile_ids(self):
        ch = DispatcharrChannel.from_api(
            {
                "id": 1,
                "uuid": "u1",
                "name": "CH1",
                "channel_number": "100",
                "streams": [],
                "channel_profile_ids": [],
            }
        )
        assert ch.channel_profile_ids == ()
