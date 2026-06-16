"""Tests for SubTaskScheduler and independent backup/channel-reset scheduling."""

import threading
import time
from unittest.mock import MagicMock, patch

from teamarr.consumers.scheduler import CronScheduler, SubTaskScheduler


class TestSubTaskScheduler:
    """Tests for the SubTaskScheduler class."""

    def test_start_stop_lifecycle(self):
        """SubTaskScheduler starts and stops cleanly."""
        task_fn = MagicMock()
        # Use a far-future cron so it doesn't fire during test
        sub = SubTaskScheduler("test", task_fn, "0 0 1 1 *")

        assert not sub.is_running
        assert sub.start()
        assert sub.is_running
        assert sub.cron_expression == "0 0 1 1 *"

        assert sub.stop(timeout=2.0)
        assert not sub.is_running
        task_fn.assert_not_called()

    def test_start_rejects_invalid_cron(self):
        """SubTaskScheduler rejects invalid cron expressions."""
        sub = SubTaskScheduler("test", MagicMock(), "not a cron")
        assert not sub.start()
        assert not sub.is_running

    def test_start_rejects_double_start(self):
        """SubTaskScheduler rejects starting twice."""
        sub = SubTaskScheduler("test", MagicMock(), "0 0 1 1 *")
        assert sub.start()
        assert not sub.start()  # Already running
        sub.stop(timeout=2.0)

    def test_stop_when_not_running(self):
        """Stopping a non-running scheduler returns True."""
        sub = SubTaskScheduler("test", MagicMock(), "0 0 1 1 *")
        assert sub.stop()

    def test_task_fires_on_cron(self):
        """SubTaskScheduler fires the task at the cron time."""
        fired = threading.Event()

        def task():
            fired.set()

        # Fire every minute — we'll wait for it
        sub = SubTaskScheduler("test", task, "* * * * *")
        sub.start()
        try:
            # Should fire within ~61 seconds
            assert fired.wait(timeout=65), "Task did not fire within 65 seconds"
        finally:
            sub.stop(timeout=2.0)

    def test_thread_is_daemon(self):
        """SubTaskScheduler thread is a daemon thread."""
        sub = SubTaskScheduler("test", MagicMock(), "0 0 1 1 *")
        sub.start()
        assert sub._thread.daemon
        sub.stop(timeout=2.0)

    def test_next_run_is_set(self):
        """SubTaskScheduler sets next_run after starting."""
        sub = SubTaskScheduler("test", MagicMock(), "0 3 * * *")
        assert sub.next_run is None
        sub.start()
        # Give the thread a moment to compute next_run
        time.sleep(0.2)
        assert sub.next_run is not None
        sub.stop(timeout=2.0)


class TestCronSchedulerSubTasks:
    """Tests for CronScheduler sub-task management."""

    def _make_scheduler(self):
        """Create a CronScheduler with mocked db_factory."""
        db_factory = MagicMock()
        return CronScheduler(
            db_factory=db_factory,
            cron_expression="0 0 1 1 *",  # Never fires
            run_on_start=False,
        )

    def test_sub_schedulers_dict_initialized(self):
        """CronScheduler initializes with empty sub_schedulers dict."""
        sched = self._make_scheduler()
        assert sched._sub_schedulers == {}

    def test_run_tasks_excludes_backup_and_channel_reset(self):
        """_run_tasks should not include backup or channel_reset."""
        sched = self._make_scheduler()
        # Patch the tasks that _run_tasks DOES call so they don't fail
        with (
            patch.object(sched, "_task_refresh_cache", return_value={"skipped": True}),
            patch.object(sched, "_task_generate_epg", return_value={"success": True}),
        ):
            results = sched._run_tasks()

        assert "backup" not in results
        assert "channel_reset" not in results
        assert "cache_refresh" in results
        assert "epg_generation" in results

    def test_run_once_includes_backup_and_channel_reset(self):
        """run_once should include backup and channel_reset for manual trigger."""
        sched = self._make_scheduler()
        with (
            patch.object(sched, "_task_refresh_cache", return_value={"skipped": True}),
            patch.object(sched, "_task_generate_epg", return_value={"success": True}),
            patch.object(sched, "_task_backup", return_value={"skipped": True}),
            patch.object(sched, "_task_channel_reset", return_value={"skipped": True}),
        ):
            results = sched.run_once()

        assert "backup" in results
        assert "channel_reset" in results

    def test_restart_sub_task_stops_and_starts(self):
        """restart_sub_task stops existing and starts new sub-scheduler."""
        sched = self._make_scheduler()

        # Manually add a mock sub-scheduler
        mock_sub = MagicMock()
        mock_sub.stop.return_value = True
        sched._sub_schedulers["backup"] = mock_sub

        # Mock settings to return disabled backup
        mock_settings = MagicMock()
        mock_settings.enabled = False

        mock_conn = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        sched._db_factory.return_value = mock_ctx

        with patch("teamarr.database.settings.get_backup_settings", return_value=mock_settings):
            sched.restart_sub_task("backup")

        # Old sub-scheduler should have been stopped
        mock_sub.stop.assert_called_once_with(timeout=5.0)
        # Since disabled, no new sub-scheduler should be created
        assert "backup" not in sched._sub_schedulers


class TestTaskBackupSimplified:
    """Tests for the simplified _task_backup (no window check)."""

    def test_backup_skips_when_disabled(self):
        """_task_backup returns skip when backups disabled."""
        sched = CronScheduler(
            db_factory=MagicMock(),
            cron_expression="0 0 1 1 *",
            run_on_start=False,
        )

        mock_settings = MagicMock()
        mock_settings.enabled = False

        mock_conn = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        sched._db_factory.return_value = mock_ctx

        with patch("teamarr.database.settings.get_backup_settings", return_value=mock_settings):
            result = sched._task_backup()

        assert result["skipped"] is True

    def test_backup_runs_without_window_check(self):
        """_task_backup runs immediately when enabled (no 1-hour window)."""
        sched = CronScheduler(
            db_factory=MagicMock(),
            cron_expression="0 0 1 1 *",
            run_on_start=False,
        )

        mock_settings = MagicMock()
        mock_settings.enabled = True
        mock_settings.path = "/tmp/backups"
        mock_settings.max_count = 7

        mock_conn = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.__enter__ = MagicMock(return_value=mock_conn)
        mock_ctx.__exit__ = MagicMock(return_value=False)
        sched._db_factory.return_value = mock_ctx

        mock_backup_result = MagicMock()
        mock_backup_result.success = True
        mock_backup_result.filename = "test.db"
        mock_backup_result.size_bytes = 1234

        mock_rotation = MagicMock()
        mock_rotation.deleted_count = 0

        mock_service = MagicMock()
        mock_service.create_backup.return_value = mock_backup_result
        mock_service.rotate_backups.return_value = mock_rotation

        with (
            patch(
                "teamarr.database.settings.get_backup_settings",
                return_value=mock_settings,
            ),
            patch(
                "teamarr.services.backup_service.create_backup_service",
                return_value=mock_service,
            ),
        ):
            result = sched._task_backup()

        assert result["executed"] is True
        assert result["success"] is True
        mock_service.create_backup.assert_called_once_with(manual=False)
