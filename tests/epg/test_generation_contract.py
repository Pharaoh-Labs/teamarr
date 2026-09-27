"""Characterization of ``run_full_generation``'s public contract (#830, Packet 0).

These tests describe what generation does *today*, not what it ought to do.
They exist so the pipeline extraction that follows (Packets 1-7) has a
behavioral baseline: stage order, phase-timing keys, cancellation checkpoints,
bootstrap/epilogue ordering, run-row uniqueness and provider-call metrics are
all compatibility contracts during that refactor. Where current behavior is
surprising it is pinned as-is and called out in a comment rather than fixed —
normalizing it here would hide a regression later.

The harness runs a *real* generation end to end against an empty isolated
database with no Dispatcharr client. Every step still executes (the phases
simply have nothing to do), which is what makes it a usable baseline: no stage
is stubbed out, so a stage that silently stops running will fail these tests.

Patch-surface inventory (Packet 0 deliverable)
----------------------------------------------
Symbols other tests import from or patch on ``teamarr.consumers.generation``,
and what must happen to each when its implementation moves:

* ``_apply_stream_ordering`` — imported directly by
  ``tests/lifecycle/test_stream_order_push_batching.py`` and
  ``tests/lifecycle/test_stream_order_convergence.py``; patched on the module by
  ``tests/test_stream_ordering_apply.py``. Must remain a *facade wrapper* that
  injects ``generation.ChannelManager``, not an assignment alias (Packet 5B).
* ``_run_stream_audit`` — imported directly by
  ``tests/lifecycle/test_stream_order_convergence.py``. Same wrapper rule.
* ``ChannelManager`` — patched on the module by ``test_generation_helpers.py``,
  ``test_stream_order_push_batching.py`` and ``test_stream_order_convergence.py``.
  Must stay a module global of ``generation`` and be reached through injection
  once ordering/audit move.
* ``_generation_lock`` / ``_generation_running`` — patched or asserted by
  ``tests/test_stream_ordering_apply.py``. Exactly one lock object; stays in
  ``generation`` and is never re-exported as a second object.
* ``_refresh_m3u_accounts``, ``_validate_channel_ranges``,
  ``_save_media_refresh_outcomes`` — imported directly by
  ``tests/epg/test_generation_helpers.py``; aliases suffice (no facade-global
  dependency).
* ``_dry_run_media_refresh`` — imported directly by ``tests/test_runtime_flags.py``;
  alias suffices.
* ``_media_server_outcome`` — imported directly by
  ``tests/test_media_server_health.py``; alias suffices.
* ``run_stream_ordering_only`` — imported by
  ``teamarr/api/routes/settings/stream_ordering.py`` inside the request handler,
  so it must keep resolving through the facade's module globals.
* ``GenerationResult`` — re-exported as ``teamarr.consumers.FullGenerationResult``.
* ``run_full_generation`` — imported by the API routes, the scheduler and
  ``teamarr.consumers``.
"""

import threading

import pytest

from teamarr.consumers import FullGenerationResult
from teamarr.consumers.generation import (
    GenerationCancelled,
    GenerationResult,
    run_full_generation,
)
from teamarr.database import get_db, init_db

# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@pytest.fixture()
def isolated_db(tmp_path, monkeypatch):
    """An empty, fully-migrated database that the whole process points at.

    ``run_full_generation`` takes a ``db_factory``, but the service layer it
    builds reaches for the process-global ``get_db``, so both have to be the
    same database for an end-to-end run.
    """
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.db"))
    init_db()
    return get_db


@pytest.fixture(autouse=True)
def _released_generation_lock():
    """Fail loudly rather than deadlocking if a test leaves the lock held."""
    from teamarr.consumers import generation as generation_mod

    yield
    if generation_mod._generation_running:  # pragma: no cover - guard
        generation_mod._generation_running = False
    if generation_mod._generation_lock.locked():  # pragma: no cover - guard
        generation_mod._generation_lock.release()
        pytest.fail("run_full_generation left the generation lock held")


class _Recorder:
    """Collects progress events in the order the facade emits them."""

    def __init__(self):
        self.events: list[tuple] = []

    def __call__(self, phase, percent, message, current, total, item_name):
        self.events.append((phase, percent, message, current, total, item_name))

    @property
    def phases(self) -> list[str]:
        return [event[0] for event in self.events]

    @property
    def percents(self) -> list[int]:
        return [event[1] for event in self.events]


def _run(db_factory, **kwargs) -> tuple[GenerationResult, _Recorder]:
    recorder = _Recorder()
    result = run_full_generation(
        db_factory=db_factory,
        dispatcharr_client=None,
        progress_callback=recorder,
        **kwargs,
    )
    return result, recorder


# ---------------------------------------------------------------------------
# GenerationResult shape (callers read these fields by name)
# ---------------------------------------------------------------------------


def test_generation_result_defaults():
    """A bare result is the shape every caller's failure path reads."""
    result = GenerationResult()

    assert result.success is True
    assert result.error is None
    assert result.started_at == 0.0
    assert result.completed_at == 0.0
    assert result.duration_seconds == 0.0
    assert result.teams_processed == 0
    assert result.teams_programmes == 0
    assert result.groups_processed == 0
    assert result.groups_programmes == 0
    assert result.programmes_total == 0
    assert result.file_written is False
    assert result.file_path is None
    assert result.file_size == 0
    assert result.run_id is None
    assert result.media_server_outcomes == []
    for name in (
        "m3u_refresh",
        "stream_ordering",
        "epg_refresh",
        "epg_association",
        "managed_team_channels",
        "managed_team_streams",
        "deletions",
        "reconciliation",
        "cleanup",
        "logo_cleanup",
        "channel_conflicts",
        "emby_refresh",
        "jellyfin_refresh",
        "channelsdvr_refresh",
        "channelsdvr_epg_refresh",
        "phase_timings",
    ):
        assert getattr(result, name) == {}, name


def test_result_fields_read_by_the_scheduler_exist():
    """The scheduler flattens the result into a dict with these exact keys."""
    result = GenerationResult()
    scheduler_dict = {
        "success": result.success,
        "error": result.error,
        "programmes_generated": result.programmes_total,
        "teams_processed": result.teams_processed,
        "teams_programmes": result.teams_programmes,
        "groups_processed": result.groups_processed,
        "groups_programmes": result.groups_programmes,
        "file_written": result.file_written,
        "file_path": result.file_path,
        "file_size": result.file_size,
        "duration_seconds": result.duration_seconds,
        "m3u_refresh": result.m3u_refresh,
        "epg_refresh": result.epg_refresh,
        "epg_association": result.epg_association,
        "deletions": result.deletions,
        "reconciliation": result.reconciliation,
        "cleanup": result.cleanup,
        "run_id": result.run_id,
    }
    assert set(scheduler_dict) == {
        "success",
        "error",
        "programmes_generated",
        "teams_processed",
        "teams_programmes",
        "groups_processed",
        "groups_programmes",
        "file_written",
        "file_path",
        "file_size",
        "duration_seconds",
        "m3u_refresh",
        "epg_refresh",
        "epg_association",
        "deletions",
        "reconciliation",
        "cleanup",
        "run_id",
    }


def test_consumers_reexports_the_result_type():
    """``teamarr.consumers.FullGenerationResult`` is the public alias."""
    assert FullGenerationResult is GenerationResult


# ---------------------------------------------------------------------------
# Legacy progress callback
# ---------------------------------------------------------------------------


def test_progress_callback_receives_six_positional_values(isolated_db):
    """The public callback signature is (phase, percent, message, current, total, item)."""
    seen: list[tuple] = []

    def callback(*args):
        seen.append(args)

    result = run_full_generation(
        db_factory=isolated_db, dispatcharr_client=None, progress_callback=callback
    )

    assert result.success is True
    assert seen, "generation emitted no progress"
    for args in seen:
        assert len(args) == 6
        phase, percent, message, current, total, item_name = args
        assert isinstance(phase, str)
        assert isinstance(percent, int)
        assert isinstance(message, str)
        assert isinstance(current, int)
        assert isinstance(total, int)
        assert isinstance(item_name, str)


def test_progress_callback_is_optional(isolated_db):
    """No callback is a no-op, not a crash."""
    result = run_full_generation(db_factory=isolated_db, dispatcharr_client=None)
    assert result.success is True


def test_progress_defaults_are_zero_and_empty(isolated_db):
    """Phase announcements that pass no counts still deliver 0/0/''."""
    _, recorder = _run(isolated_db)

    init_events = [e for e in recorder.events if e[0] == "init"]
    assert init_events == [("init", 3, "Refreshing M3U accounts...", 0, 0, "")]


# ---------------------------------------------------------------------------
# Progress sequence
# ---------------------------------------------------------------------------


def test_phase_names_and_percentages(isolated_db):
    """The phase/percent sequence of an otherwise-empty run.

    Pinned verbatim: the frontend keys off these phase names and the SSE
    payload carries these percentages.
    """
    _, recorder = _run(isolated_db)

    assert recorder.events[0] == ("init", 3, "Refreshing M3U accounts...", 0, 0, "")
    assert recorder.events[1] == ("teams", 5, "Processing teams...", 0, 0, "")
    assert recorder.events[-1] == ("complete", 100, "Generation complete", 0, 0, "")

    assert recorder.phases == [
        "init",
        "teams",
        "groups",  # teams -> groups transition announcement
        "groups",  # group processing (nothing configured)
        "groups",  # global channel reassignment, still labelled "groups"
        "ordering",
        "saving",
        "lifecycle",
        "reconciliation",
        "cleanup",
        "complete",
    ]


def test_raw_progress_percentages_are_not_monotonic(isolated_db):
    """Characterization of a real wrinkle, not an endorsement of it.

    Global channel reassignment reports 94% under the "groups" phase, and the
    ordering stage that runs *after* it reports 93%. The raw callback stream
    therefore goes backwards. Displayed progress stays monotonic only because
    ``generation_status.update_status`` clamps it (see
    ``test_generation_status.py``). Packet 3 must preserve both halves of this.
    """
    _, recorder = _run(isolated_db)

    percents = recorder.percents
    assert percents != sorted(percents), "raw percentages unexpectedly monotonic"

    reassign = next(i for i, e in enumerate(recorder.events) if e[1] == 94)
    ordering = next(i for i, e in enumerate(recorder.events) if e[0] == "ordering")
    assert reassign < ordering
    assert recorder.events[ordering][1] == 93


# ---------------------------------------------------------------------------
# Stage order and phase timings
# ---------------------------------------------------------------------------


def test_phase_timing_keys_and_order(isolated_db):
    """``phase_timings`` insertion order is the timed-stage order.

    Note ``team_channels`` (#826) sits between channel reassignment and stream
    ordering, and that ``stream_audit`` covers stale-group detection plus the
    audit even though neither has a cancellation checkpoint.
    """
    result, _ = _run(isolated_db)

    assert list(result.phase_timings) == [
        "m3u_refresh",
        "teams",
        "groups",
        "channel_reassign",
        "team_channels",
        "stream_ordering",
        "xmltv_save",
        "dispatcharr_epg_refresh",
        "deletions",
        "reconciliation",
        "stream_audit",
        "cleanup",
    ]
    assert all(isinstance(v, float) for v in result.phase_timings.values())


def test_fixed_stage_list_keeps_phase_order_and_checkpoints():
    """Packet 7 must not alter order or add plugin stages during facade cleanup."""
    from teamarr.consumers import generation as generation_mod

    assert [
        (stage.run.__name__, stage.cancellation_before, stage.timing_name)
        for stage in generation_mod._FULL_GENERATION_STAGES
    ] == [
        ("_stage_m3u_refresh", True, "m3u_refresh"),
        ("_stage_teams", True, "teams"),
        ("_stage_prepare_team_channels", False, None),
        ("_stage_groups", True, "groups"),
        ("_stage_channel_reassign", True, "channel_reassign"),
        ("_stage_team_channels", True, "team_channels"),
        ("_stage_stream_ordering", True, "stream_ordering"),
        ("_stage_xmltv_save", True, "xmltv_save"),
        ("_stage_lifecycle_prepare", False, None),
        ("_stage_dispatcharr_epg", True, "dispatcharr_epg_refresh"),
        ("_stage_media_jobs", True, None),
        ("_stage_deletions", True, "deletions"),
        ("_stage_reconciliation", True, "reconciliation"),
        ("_stage_stream_audit", False, "stream_audit"),
        ("_stage_cleanup", True, "cleanup"),
    ]


def test_untimed_work_is_billed_to_the_next_timing_mark(isolated_db):
    """Lifecycle construction has no key of its own.

    ``create_lifecycle_service`` + ``compute_external_occupied`` +
    ``sync_stream_profiles`` run between the XMLTV mark and the Dispatcharr
    mark, so their cost lands in ``dispatcharr_epg_refresh``. Surprising, and
    deliberately preserved (plan §6, "do not normalize surprising timing").
    """
    result, _ = _run(isolated_db)

    keys = list(result.phase_timings)
    assert keys[keys.index("xmltv_save") + 1] == "dispatcharr_epg_refresh"
    assert "lifecycle_prepare" not in result.phase_timings
    assert "media_jobs" not in result.phase_timings


# ---------------------------------------------------------------------------
# Bootstrap and epilogue ordering
# ---------------------------------------------------------------------------


def test_run_bootstrap_order(isolated_db, monkeypatch):
    """Counter, metric reset, shared service, then settings — before any stage."""
    import teamarr.consumers.generation as generation_mod
    import teamarr.consumers.stream_match_cache as cache_mod
    import teamarr.database.settings as settings_mod
    from teamarr.utilities import call_metrics

    order: list[str] = []

    def _trace(module, name, label):
        original = getattr(module, name)

        def wrapper(*args, **kwargs):
            order.append(label)
            return original(*args, **kwargs)

        monkeypatch.setattr(module, name, wrapper)

    _trace(cache_mod, "increment_generation_counter", "counter")
    _trace(call_metrics, "reset", "metrics_reset")
    _trace(generation_mod, "create_default_service", "service")
    _trace(settings_mod, "get_epg_settings", "settings:epg")
    _trace(settings_mod, "get_dispatcharr_settings", "settings:dispatcharr")
    _trace(settings_mod, "get_display_settings", "settings:display")
    _trace(generation_mod, "_refresh_m3u_accounts", "stage:m3u")

    def first_stage_marker(*args, **kwargs):
        order.append("stage:teams")
        raise GenerationCancelled("stop after bootstrap")

    monkeypatch.setattr("teamarr.consumers.process_all_teams", first_stage_marker)

    result, _ = _run(isolated_db)

    assert result.success is False
    assert order == [
        "counter",
        "metrics_reset",
        "service",
        "settings:epg",
        "settings:dispatcharr",
        "settings:display",
        # no "stage:m3u" — skipped outright without a Dispatcharr client
        "stage:teams",
    ]


def test_success_epilogue_order(isolated_db, monkeypatch):
    """Stats finalize, then result fields, the complete event, then cache flush."""
    import teamarr.consumers.generation as generation_mod

    order: list[str] = []

    original_finalize = generation_mod._finalize_stats_run

    def traced_finalize(*args, **kwargs):
        order.append("finalize_stats")
        return original_finalize(*args, **kwargs)

    original_flush = generation_mod.flush_shared_cache

    def traced_flush(*args, **kwargs):
        order.append("flush_cache")
        return original_flush(*args, **kwargs)

    monkeypatch.setattr(generation_mod, "_finalize_stats_run", traced_finalize)
    monkeypatch.setattr(generation_mod, "flush_shared_cache", traced_flush)

    def callback(phase, percent, message, current, total, item_name):
        if phase == "complete":
            order.append("complete_event")

    result = run_full_generation(
        db_factory=isolated_db, dispatcharr_client=None, progress_callback=callback
    )

    assert order == ["finalize_stats", "complete_event", "flush_cache"]
    assert result.success is True
    assert result.completed_at >= result.started_at > 0
    assert result.duration_seconds == round(result.completed_at - result.started_at, 1)


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


def test_full_run_has_twelve_cancellation_checkpoints(isolated_db, monkeypatch):
    """Count the checkpoints a complete run passes through.

    Packet 3 marks stages ``cancellation_before=True``; this is the number it
    has to reproduce. Stale-group detection, the audit, stats finalization and
    the detached media-refresh start deliberately have none.
    """
    calls = {"n": 0}
    import teamarr.consumers.generation_status as status_mod

    original = status_mod.is_cancellation_requested

    def counting():
        calls["n"] += 1
        return original()

    monkeypatch.setattr(status_mod, "is_cancellation_requested", counting)

    result, _ = _run(isolated_db)

    assert result.success is True
    assert calls["n"] == 12


@pytest.mark.parametrize(
    ("stop_at", "expected_timings"),
    [
        (1, []),
        (2, ["m3u_refresh"]),
        (3, ["m3u_refresh", "teams"]),
        (
            7,
            [
                "m3u_refresh",
                "teams",
                "groups",
                "channel_reassign",
                "team_channels",
                "stream_ordering",
            ],
        ),
    ],
)
def test_cancellation_stops_at_the_checkpoint(
    isolated_db, monkeypatch, stop_at, expected_timings
):
    """Cancelling at checkpoint N leaves exactly the stages before it timed."""
    import teamarr.consumers.generation_status as status_mod

    calls = {"n": 0}

    def cancel_at_n():
        calls["n"] += 1
        return calls["n"] >= stop_at

    monkeypatch.setattr(status_mod, "is_cancellation_requested", cancel_at_n)

    result, _ = _run(isolated_db)

    assert result.success is False
    assert result.error == "Cancelled by user"
    assert list(result.phase_timings) == expected_timings


def test_cancelled_run_populates_timing_fields_and_persists(isolated_db, monkeypatch):
    """A cancelled run still gets completed_at/duration and a saved run row."""
    import teamarr.consumers.generation_status as status_mod
    from teamarr.database.stats import get_run

    monkeypatch.setattr(status_mod, "is_cancellation_requested", lambda: True)

    result, _ = _run(isolated_db)

    assert result.success is False
    assert result.error == "Cancelled by user"
    assert result.completed_at > 0
    assert result.duration_seconds == round(result.completed_at - result.started_at, 1)
    assert result.run_id is not None

    with isolated_db() as conn:
        saved = get_run(conn, result.run_id)
    assert saved is not None
    assert saved.status == "cancelled"
    assert saved.error_message == "Cancelled by user"


def test_failed_run_persists_the_error(isolated_db, monkeypatch):
    """An unexpected exception becomes a failed result and a failed run row."""
    from teamarr.database.stats import get_run

    def boom(*args, **kwargs):
        raise RuntimeError("team processing exploded")

    monkeypatch.setattr("teamarr.consumers.process_all_teams", boom)

    result, _ = _run(isolated_db)

    assert result.success is False
    assert result.error == "team processing exploded"
    assert result.completed_at > 0

    with isolated_db() as conn:
        saved = get_run(conn, result.run_id)
    assert saved is not None
    assert saved.status == "failed"
    assert saved.error_message == "team processing exploded"


# ---------------------------------------------------------------------------
# Run-row uniqueness and the duplicate guards
# ---------------------------------------------------------------------------


def _full_epg_run_count(db_factory) -> int:
    with db_factory() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM processing_runs WHERE run_type = 'full_epg'"
        ).fetchone()
    return row["n"]


def test_one_processing_row_per_accepted_run(isolated_db):
    """Exactly one ``full_epg`` row per accepted generation."""
    assert _full_epg_run_count(isolated_db) == 0

    result, _ = _run(isolated_db)

    assert result.success is True
    assert result.run_id is not None
    assert _full_epg_run_count(isolated_db) == 1


def test_process_lock_rejects_a_duplicate_without_creating_a_row(isolated_db):
    """The in-process lock short-circuits before the run row is created."""
    from teamarr.consumers import generation as generation_mod

    assert generation_mod._generation_lock.acquire(blocking=False)
    try:
        result, recorder = _run(isolated_db)
    finally:
        generation_mod._generation_lock.release()

    assert result.success is False
    assert result.error == "Generation already in progress"
    assert result.run_id is None
    assert recorder.events == []
    assert _full_epg_run_count(isolated_db) == 0


def test_reorder_only_cannot_overlap_an_active_full_generation(isolated_db, monkeypatch):
    from teamarr.consumers import generation as generation_mod

    original_ordering = generation_mod._apply_stream_ordering
    ordering_calls = []

    def traced_ordering(*args, **kwargs):
        ordering_calls.append(kwargs["manual"])
        return original_ordering(*args, **kwargs)

    monkeypatch.setattr(generation_mod, "_apply_stream_ordering", traced_ordering)
    rejected = []

    def callback(phase, percent, message, current, total, item_name):
        if phase == "init":
            rejected.append(generation_mod.run_stream_ordering_only(isolated_db, None))

    result = run_full_generation(isolated_db, progress_callback=callback)

    assert result.success is True
    assert rejected == [None]
    assert ordering_calls == [False]  # full-generation stage only
    assert generation_mod._generation_running is False
    assert not generation_mod._generation_lock.locked()


def test_database_guard_rejects_a_recent_running_run(isolated_db):
    """A ``running`` full_epg row younger than five minutes blocks a new run."""
    from teamarr.database.stats import create_run

    with isolated_db() as conn:
        create_run(conn, run_type="full_epg")
    assert _full_epg_run_count(isolated_db) == 1

    result, _ = _run(isolated_db)

    assert result.success is False
    assert result.error == "Generation already in progress"
    assert result.run_id is None
    assert _full_epg_run_count(isolated_db) == 1


def test_lock_is_released_after_every_outcome(isolated_db, monkeypatch):
    """Success, failure and cancellation all release the lock exactly once."""
    from teamarr.consumers import generation as generation_mod

    def assert_free():
        assert generation_mod._generation_running is False
        assert generation_mod._generation_lock.acquire(blocking=False)
        generation_mod._generation_lock.release()

    _run(isolated_db)
    assert_free()

    monkeypatch.setattr(
        "teamarr.consumers.process_all_teams", lambda **kw: (_ for _ in ()).throw(RuntimeError("x"))
    )
    _run(isolated_db)
    assert_free()


def test_concurrent_runs_produce_one_row(isolated_db):
    """Two threads racing into generation: one runs, one is rejected."""
    results: list[GenerationResult] = []
    barrier = threading.Barrier(2)

    def worker():
        barrier.wait()
        results.append(
            run_full_generation(db_factory=isolated_db, dispatcharr_client=None)
        )

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert len(results) == 2
    assert sorted(r.success for r in results) == [False, True]
    rejected = next(r for r in results if not r.success)
    assert rejected.error == "Generation already in progress"
    assert _full_epg_run_count(isolated_db) == 1


# ---------------------------------------------------------------------------
# Provider-call metrics
# ---------------------------------------------------------------------------


def test_provider_call_metrics_are_reset_then_persisted(isolated_db, monkeypatch):
    """Counter is cleared at run start and snapshotted onto the run row.

    NOTE for Packet 1: the *totals* here are not a permanent constant. Sharing
    one ``SportsDataService`` across team and group processing warms the cache
    and legitimately lowers call counts. What must not change is the metric
    schema (``provider:endpoint`` keys), the reset-at-start timing, and the
    persistence into ``extra_metrics``.
    """
    import teamarr.consumers.generation as generation_mod
    from teamarr.database.stats import get_run
    from teamarr.utilities import call_metrics

    # Stale counts from before the run must not leak into it.
    call_metrics.record_call("stale", "leftover")

    original_service = generation_mod.create_default_service

    def service_then_record(*args, **kwargs):
        service = original_service(*args, **kwargs)
        call_metrics.record_call("espn", "https://site.api.espn.com/v2/sports/summary?event=1")
        call_metrics.record_call("espn", "summary")
        call_metrics.record_call("bellmedia", "schedule")
        return service

    monkeypatch.setattr(generation_mod, "create_default_service", service_then_record)

    result, _ = _run(isolated_db)

    assert result.success is True
    with isolated_db() as conn:
        saved = get_run(conn, result.run_id)

    assert saved is not None
    calls = saved.extra_metrics["provider_calls"]
    assert "stale:leftover" not in calls
    assert calls["espn:summary"] == 2
    assert calls["bellmedia:schedule"] == 1
    assert saved.extra_metrics["provider_calls_total"] == 3


def test_run_extra_metrics_keys(isolated_db):
    """The ``extra_metrics`` keys a completed run always carries."""
    from teamarr.database.stats import get_run

    result, _ = _run(isolated_db)

    with isolated_db() as conn:
        saved = get_run(conn, result.run_id)

    assert saved is not None
    assert saved.status == "completed"
    for key in (
        "teams_processed",
        "groups_processed",
        "groups",
        "file_written",
        "provider_calls",
        "provider_calls_total",
        "phase_timings",
    ):
        assert key in saved.extra_metrics, key
    # Optional keys: only present when there is something to report.
    assert "media_servers" not in saved.extra_metrics
    assert saved.channels_active == 0
