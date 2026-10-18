"""Cleanup safety on a fetch that yields nothing (bpqb.8, #907)."""

import contextlib
import sqlite3

from teamarr.database.groups import create_group, get_group
from tests.helpers import SCHEMA_PATH


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA_PATH.read_text())
    return conn


def _factory(conn):
    @contextlib.contextmanager
    def factory():
        yield conn
        conn.commit()

    return factory


# ---------------------------------------------------------------------------
# Cleanup safety (bpqb.8)
#
# A source whose group stops yielding streams (provider rename, M3U outage)
# must NEVER cascade into channel deletion. The guarantee lives in
# _process_group_internal's short-circuits: an empty fetch and an
# all-filtered run return before cleanup_deleted_streams or any lifecycle
# call. A zero-match run with a real pool DOES reach the lifecycle since
# #907 — but only as a changed-only cleanup (a stream still present in the
# pool under new content is detached; absence is never read as removal) and
# never the create step. Written for pattern-bound sources (#450, retired in
# #1056); the guarantee is about the fetch result, not the binding.
# ---------------------------------------------------------------------------


def _tripwire(name):
    def _fail(*args, **kwargs):
        raise AssertionError(f"{name} must not be called on this path")

    return _fail


def _seeded_group_db():
    """Schema DB with the template requirement satisfied and one real group."""
    conn = _db()
    cur = conn.execute("INSERT INTO templates (name, template_type) VALUES ('T', 'event')")
    conn.execute("INSERT INTO subscription_templates (template_id) VALUES (?)", (cur.lastrowid,))
    gid = create_group(conn, name="EPL", leagues=["eng.1"], m3u_group_id=999)
    conn.commit()
    return conn, get_group(conn, gid)


class TestCleanupSafety:
    def _processor(self, conn):
        from unittest.mock import MagicMock

        from teamarr.consumers.event_group_processor import EventGroupProcessor

        # Inject a stub service: the default one loads league mappings from the
        # global DB path, which doesn't exist in CI (and none of these paths
        # reach the provider layer anyway).
        return EventGroupProcessor(db_factory=_factory(conn), service=MagicMock())

    def test_empty_fetch_short_circuits_before_any_cleanup(self, monkeypatch):
        from datetime import date

        conn, group = _seeded_group_db()
        proc = self._processor(conn)
        monkeypatch.setattr(proc, "_fetch_streams", lambda g: [])
        for name in (
            "_filter_streams",
            "_match_streams",
            "_process_channels",
            "_get_lifecycle_service",
        ):
            monkeypatch.setattr(proc, name, _tripwire(name))

        result = proc._process_group_internal(conn, group, date.today())

        assert result.errors == ["No streams found for group"]
        assert result.channels_deleted == 0

    def test_all_filtered_short_circuits_before_matching(self, monkeypatch):
        from datetime import date

        from teamarr.services.stream_filter import FilterResult

        conn, group = _seeded_group_db()
        proc = self._processor(conn)
        monkeypatch.setattr(
            proc, "_fetch_streams", lambda g: [{"id": 11, "name": "Arsenal vs Spurs"}]
        )
        monkeypatch.setattr(
            proc,
            "_filter_streams",
            lambda streams, g: ([], FilterResult(total_input=1, filtered_exclude=1)),
        )
        for name in ("_match_streams", "_process_channels", "_get_lifecycle_service"):
            monkeypatch.setattr(proc, name, _tripwire(name))

        result = proc._process_group_internal(conn, group, date.today())

        assert result.errors == ["All streams filtered out by regex patterns"]
        assert result.channels_deleted == 0

    def test_zero_matches_runs_changed_only_cleanup_never_create(self, monkeypatch):
        """#907: a zero-match run reaches the lifecycle, but only its cleanup step.

        The pool is real (fetch and filter both passed streams), so a stream
        that rotated under the same Dispatcharr id must be detached. The
        guarantee is preserved by the mode: ``changed_only=True`` and no
        create call.
        """
        from datetime import date
        from unittest.mock import MagicMock

        from teamarr.consumers.lifecycle import StreamProcessResult
        from teamarr.consumers.matching.matcher import BatchMatchResult
        from teamarr.services.stream_filter import FilterResult

        conn, group = _seeded_group_db()
        proc = self._processor(conn)
        streams = [{"id": 11, "name": "Arsenal vs Spurs"}]
        monkeypatch.setattr(proc, "_fetch_streams", lambda g: list(streams))
        monkeypatch.setattr(
            proc,
            "_filter_streams",
            lambda s, g: (list(streams), FilterResult(total_input=1, passed_count=1)),
        )
        monkeypatch.setattr(proc, "_match_streams", lambda *a, **k: BatchMatchResult())

        lifecycle = MagicMock()
        lifecycle.process_scheduled_deletions.return_value = StreamProcessResult()
        cleanup = StreamProcessResult()
        cleanup.deleted.append({"channel_id": 1, "reason": "1 content-changed"})
        lifecycle.cleanup_deleted_streams.return_value = cleanup
        monkeypatch.setattr(proc, "_get_lifecycle_service", lambda: lifecycle)

        result = proc._process_group_internal(conn, group, date.today())

        assert result.errors == []
        assert result.streams_matched == 0
        lifecycle.cleanup_deleted_streams.assert_called_once()
        kwargs = lifecycle.cleanup_deleted_streams.call_args.kwargs
        assert kwargs["changed_only"] is True
        assert kwargs["matched_streams"] == []
        assert lifecycle.cleanup_deleted_streams.call_args.args[1] == {11: streams[0]}
        lifecycle.process_matched_streams.assert_not_called()
        assert result.channels_deleted == 1

    def test_matched_run_keeps_full_cleanup(self, monkeypatch):
        """The matched path is unchanged: missing streams still count (changed_only off)."""
        from unittest.mock import MagicMock

        from teamarr.consumers.lifecycle import StreamProcessResult

        conn, group = _seeded_group_db()
        proc = self._processor(conn)
        lifecycle = MagicMock()
        lifecycle.process_scheduled_deletions.return_value = StreamProcessResult()
        lifecycle.cleanup_deleted_streams.return_value = StreamProcessResult()
        lifecycle.process_matched_streams.return_value = StreamProcessResult()
        monkeypatch.setattr(proc, "_get_lifecycle_service", lambda: lifecycle)

        matched = [{"stream": {"id": 11, "name": "Arsenal vs Spurs"}, "event": None}]
        proc._process_channels(matched, group, conn, current_streams={11: {"name": "x"}})

        assert lifecycle.cleanup_deleted_streams.call_args.kwargs["changed_only"] is False
        lifecycle.process_matched_streams.assert_called_once()


# ---------------------------------------------------------------------------
# A source reads one M3U group (#1089)
# ---------------------------------------------------------------------------


class TestUnboundSourceFetchesNothing:
    def test_no_group_id_reads_nothing_and_never_lists_every_stream(self):
        from types import SimpleNamespace

        from teamarr.consumers.event_group_processor.stream_fetcher import StreamFetcher

        calls = []

        def list_streams(**kwargs):
            calls.append(kwargs)
            return [SimpleNamespace(id=1, name="Arsenal v Chelsea")]

        fetcher = StreamFetcher.__new__(StreamFetcher)
        m3u = SimpleNamespace(list_streams=list_streams)
        fetcher._dispatcharr_client = SimpleNamespace(m3u=m3u)
        fetcher._db_factory = None
        group = SimpleNamespace(id=5, name="LIVE | Scottish Football", is_channel_source=False)
        group.m3u_group_id = None

        assert fetcher._fetch_streams(group) == []
        assert calls == []
