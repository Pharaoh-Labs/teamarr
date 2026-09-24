"""Unified EPG generation workflow.

This module provides the single source of truth for EPG generation.
Both the streaming API endpoint and the background scheduler call this.
"""

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

from teamarr.consumers.generation_pipeline import channel_steps, media_refresh, stats
from teamarr.consumers.generation_pipeline.models import (
    CallbackCancellationToken,
    GenerationCancelled,
    GenerationContext,
    GenerationResult,
    GenerationSettingsSnapshot,
    ProgressCallback,
    legacy_progress_reporter,
)
from teamarr.consumers.generation_pipeline.phases import (
    channel_output,
    post_processing,
    preparation,
    processing,
)
from teamarr.consumers.generation_pipeline.runner import GenerationStage, StageRunner
from teamarr.dispatcharr.managers import ChannelManager
from teamarr.services import create_default_service
from teamarr.services.sports_data import flush_shared_cache
from teamarr.utilities import call_metrics

logger = logging.getLogger(__name__)

# GenerationCancelled, GenerationResult and ProgressCallback now live in
# generation_pipeline.models and are re-exported here: this module is the
# public composition root, and the API, the scheduler, teamarr.consumers and
# several test modules import them from this path.
__all__ = [
    "GenerationCancelled",
    "GenerationResult",
    "ProgressCallback",
    "run_full_generation",
    "run_stream_ordering_only",
]


# Global lock to prevent concurrent EPG generation runs
_generation_lock = threading.Lock()
_generation_running = False

class _PhaseTimer:
    """Records elapsed wall time between phase marks."""

    def __init__(self, timings: dict):
        self._timings = timings
        self._last = time.time()

    def mark(self, phase: str) -> None:
        now = time.time()
        self._timings[phase] = round(self._timings.get(phase, 0.0) + (now - self._last), 2)
        self._last = now


def run_full_generation(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None = None,
    progress_callback: ProgressCallback | None = None,
    manual: bool = False,
) -> GenerationResult:
    """Run the fixed, complete EPG generation workflow."""
    global _generation_running

    if not _generation_lock.acquire(blocking=False):
        logger.warning("[GENERATION] Already in progress, skipping duplicate run")
        return GenerationResult(success=False, error="Generation already in progress")
    if _generation_running:
        _generation_lock.release()
        logger.warning("[GENERATION] Already in progress (flag check), skipping")
        return GenerationResult(success=False, error="Generation already in progress")
    _generation_running = True

    from teamarr.consumers.generation_status import cancel_generation, is_cancellation_requested
    from teamarr.database.settings import (
        get_dispatcharr_settings,
        get_display_settings,
        get_epg_settings,
    )
    from teamarr.database.stats import create_run

    result = GenerationResult(started_at=time.time())
    report_progress = legacy_progress_reporter(progress_callback)
    try:
        with db_factory() as conn:
            try:
                conn.execute("BEGIN IMMEDIATE")
                recent_running = conn.execute(
                    """SELECT id FROM processing_runs
                       WHERE run_type = 'full_epg' AND status = 'running'
                       AND started_at > datetime('now', '-5 minutes') LIMIT 1"""
                ).fetchone()
                if recent_running:
                    conn.execute("ROLLBACK")
                    _generation_running = False
                    _generation_lock.release()
                    logger.warning(
                        "[GENERATION] Already in progress (run %d), skipping",
                        recent_running["id"],
                    )
                    return GenerationResult(success=False, error="Generation already in progress")
                stats_run = create_run(conn, run_type="full_epg")
                result.run_id = stats_run.id
            except Exception as exc:
                try:
                    conn.execute("ROLLBACK")
                except Exception as rollback_err:
                    logger.debug(
                        "[GENERATION] Rollback failed during lock acquisition: %s", rollback_err
                    )
                _generation_running = False
                _generation_lock.release()
                logger.error("[GENERATION] Failed to acquire lock: %s", exc)
                return GenerationResult(success=False, error=f"Failed to acquire lock: {exc}")

        from teamarr.consumers.stream_match_cache import increment_generation_counter

        current_generation = increment_generation_counter(db_factory)
        logger.info("[GENERATION] Starting with cache generation %d", current_generation)
        call_metrics.reset()
        shared_service = create_default_service()
        with db_factory() as conn:
            settings = GenerationSettingsSnapshot(
                epg=get_epg_settings(conn),
                dispatcharr=get_dispatcharr_settings(conn),
                display=get_display_settings(conn),
            )
        context = GenerationContext(
            db_factory=db_factory,
            dispatcharr_client=dispatcharr_client,
            manual=manual,
            settings=settings,
            sports_service=shared_service,
            progress=report_progress,
            cancellation=CallbackCancellationToken(requested=is_cancellation_requested),
            result=result,
            stats_run=stats_run,
            current_generation=current_generation,
        )
        StageRunner(_PhaseTimer(result.phase_timings).mark).run(context, _FULL_GENERATION_STAGES)

        logger.info("[GENERATION] Phase timings (s): %s", result.phase_timings)
        _finalize_stats_run(
            stats_run,
            result,
            context.team_result,
            context.group_result,
            context.channels_deleted_count,
            db_factory,
        )
        if context.media_jobs and result.run_id is not None:
            _start_media_server_refresh(db_factory, result.run_id, context.media_jobs)
        result.completed_at = time.time()
        result.duration_seconds = round(result.completed_at - result.started_at, 1)
        result.success = True
        context.report("complete", 100, "Generation complete")
        flushed = flush_shared_cache()
        if flushed > 0:
            logger.debug("[CACHE] Flushed %d entries to SQLite", flushed)
    except GenerationCancelled:
        elapsed = round(time.time() - result.started_at, 1)
        logger.info("[GENERATION] Cancelled by user after %.1fs", elapsed)
        result.success = False
        result.error = "Cancelled by user"
        result.completed_at = time.time()
        result.duration_seconds = elapsed
        cancel_generation()
        try:
            from teamarr.database.stats import save_run

            stats_run.complete(status="cancelled", error="Cancelled by user")
            with db_factory() as conn:
                save_run(conn, stats_run)
        except Exception as save_err:
            logger.warning("[GENERATION] Failed to save cancelled run stats: %s", save_err)
    except Exception as exc:
        logger.exception("[GENERATION] Failed: %s", exc)
        result.success = False
        result.error = str(exc)
        result.completed_at = time.time()
        result.duration_seconds = round(result.completed_at - result.started_at, 1)
        try:
            from teamarr.database.stats import save_run

            stats_run.complete(status="failed", error=str(exc))
            with db_factory() as conn:
                save_run(conn, stats_run)
        except Exception as save_err:
            logger.warning("[GENERATION] Failed to save failed run stats: %s", save_err)
    finally:
        _generation_running = False
        if _generation_lock.locked():
            _generation_lock.release()
    return result


def _stage_m3u_refresh(context: GenerationContext) -> None:
    """Facade seam for the preparation phase's M3U refresh."""
    preparation.stage_m3u_refresh(context, refresh_m3u_accounts=_refresh_m3u_accounts)


def _stage_teams(context: GenerationContext) -> None:
    """Facade seam for team processing and its legacy patch path."""
    from teamarr.consumers import process_all_teams

    processing.stage_teams(context, team_processor=process_all_teams)


def _stage_prepare_team_channels(context: GenerationContext) -> None:
    """Facade seam for managed team-channel preparation."""
    preparation.stage_prepare_team_channels(context)


def _stage_groups(context: GenerationContext) -> None:
    """Facade seam for group processing and its legacy patch paths."""
    from teamarr.consumers import process_all_event_groups
    from teamarr.consumers.lifecycle import compute_external_occupied

    processing.stage_groups(
        context,
        group_processor=process_all_event_groups,
        external_occupied_provider=compute_external_occupied,
        validate_channel_ranges=_validate_channel_ranges,
    )


def _stage_channel_reassign(context: GenerationContext) -> None:
    """Facade seam for global channel reassignment."""
    channel_output.stage_channel_reassign(context, sync_global_channels=_sync_global_channels)


def _stage_team_channels(context: GenerationContext) -> None:
    assert context.team_channel_manager is not None
    try:
        context.result.managed_team_channels = context.team_channel_manager.sync(
            relayout=context.relayout
        )
        context.result.managed_team_streams = context.team_channel_manager.sync_stream_memberships(
            context.team_matched_streams, completed_group_ids=context.team_completed_groups
        )
    except Exception as exc:  # noqa: BLE001 - per-step isolation
        logger.exception("[GENERATION] Managed team channel sync failed: %s", exc)
        context.result.managed_team_channels = {"error": str(exc)}


def _stage_stream_ordering(context: GenerationContext) -> None:
    """Facade seam for stream ordering and its patched manager dependency."""
    def apply_ordering(db_factory, dispatcharr_client, report, manual):
        return _apply_stream_ordering(db_factory, dispatcharr_client, report, manual=manual)

    channel_steps.stage_stream_ordering(
        context,
        apply_ordering=apply_ordering,
    )


def _stage_xmltv_save(context: GenerationContext) -> None:
    """Facade seam for XMLTV publication."""
    channel_output.stage_xmltv_save(context)


def _stage_lifecycle_prepare(context: GenerationContext) -> None:
    """Facade seam for lifecycle construction and its dynamic factory."""
    from teamarr.consumers import create_lifecycle_service

    post_processing.stage_lifecycle_prepare(context, lifecycle_factory=create_lifecycle_service)


def _stage_dispatcharr_epg(context: GenerationContext) -> None:
    """Facade seam for Dispatcharr EPG refresh cancellation behavior."""
    from teamarr.consumers.generation_status import is_cancellation_requested

    post_processing.stage_dispatcharr_epg(context, cancellation_requested=is_cancellation_requested)


def _stage_media_jobs(context: GenerationContext) -> None:
    """Facade seam for media-job discovery and DRY_RUN suppression."""
    media_refresh.stage_media_jobs(
        context,
        get_jobs=_get_media_refresh_jobs,
        dry_run_refresh=_dry_run_media_refresh,
    )


def _stage_deletions(context: GenerationContext) -> None:
    """Facade seam for scheduled deletion processing."""
    post_processing.stage_deletions(context)


def _stage_reconciliation(context: GenerationContext) -> None:
    """Facade seam for reconciliation's dynamic service and settings reads."""
    from teamarr.consumers import create_reconciler
    from teamarr.database.channels import get_reconciliation_settings

    post_processing.stage_reconciliation(
        context,
        reconciler_factory=create_reconciler,
        reconciliation_settings=get_reconciliation_settings,
    )


def _stage_stream_audit(context: GenerationContext) -> None:
    """Facade seam for stale-group and stream-audit diagnostics."""
    from teamarr.consumers import detect_stale_groups

    post_processing.stage_stream_audit(
        context,
        stale_group_detector=detect_stale_groups,
        stream_audit=_run_stream_audit,
    )


def _stage_cleanup(context: GenerationContext) -> None:
    """Facade seam for cleanup work and compatibility helper patching."""
    stats.stage_cleanup(context, cleanup_tasks=_run_cleanup_tasks)


_FULL_GENERATION_STAGES = (
    GenerationStage(_stage_m3u_refresh, cancellation_before=True, timing_name="m3u_refresh"),
    GenerationStage(_stage_teams, cancellation_before=True, timing_name="teams"),
    GenerationStage(_stage_prepare_team_channels),
    GenerationStage(_stage_groups, cancellation_before=True, timing_name="groups"),
    GenerationStage(
        _stage_channel_reassign, cancellation_before=True, timing_name="channel_reassign"
    ),
    GenerationStage(_stage_team_channels, cancellation_before=True, timing_name="team_channels"),
    GenerationStage(
        _stage_stream_ordering, cancellation_before=True, timing_name="stream_ordering"
    ),
    GenerationStage(_stage_xmltv_save, cancellation_before=True, timing_name="xmltv_save"),
    GenerationStage(_stage_lifecycle_prepare),
    GenerationStage(
        _stage_dispatcharr_epg,
        cancellation_before=True,
        timing_name="dispatcharr_epg_refresh",
    ),
    GenerationStage(_stage_media_jobs, cancellation_before=True),
    GenerationStage(_stage_deletions, cancellation_before=True, timing_name="deletions"),
    GenerationStage(_stage_reconciliation, cancellation_before=True, timing_name="reconciliation"),
    GenerationStage(_stage_stream_audit, timing_name="stream_audit"),
    GenerationStage(_stage_cleanup, cancellation_before=True, timing_name="cleanup"),
)




def _get_media_refresh_jobs(db_factory: Callable[[], Any]) -> list[tuple[str, Any]]:
    """Compatibility wrapper for extracted media-job discovery."""
    return media_refresh.get_media_refresh_jobs(db_factory)


def _start_media_server_refresh(
    db_factory: Callable[[], Any], run_id: int, jobs: list[tuple[str, Any]]
) -> None:
    """Compatibility wrapper for detached media refresh startup."""
    media_refresh.start_media_server_refresh(db_factory, run_id, jobs)


def _save_media_refresh_outcomes(
    db_factory: Callable[[], Any], run_id: int, outcomes: list[dict], duration: float
) -> None:
    """Compatibility wrapper for media outcome persistence."""
    media_refresh.save_media_refresh_outcomes(db_factory, run_id, outcomes, duration)


def _dry_run_media_refresh(result: Any, jobs: list[tuple[str, Any]]) -> bool:
    """Compatibility wrapper for DRY_RUN media handling."""
    return media_refresh.dry_run_media_refresh(result, jobs)


def _media_server_outcome(kind: str, label: str, outcome: dict) -> dict:
    """Compatibility wrapper for one flattened media-server outcome."""
    return media_refresh.media_server_outcome(kind, label, outcome)


def _run_cleanup_tasks(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
    update_progress: Callable,
) -> dict:
    """Compatibility wrapper for extracted cleanup work."""
    return stats.run_cleanup_tasks(db_factory, dispatcharr_client, update_progress)


def _finalize_stats_run(
    stats_run: Any,
    result: GenerationResult,
    team_result: Any,
    group_result: Any,
    channels_deleted_count: int,
    db_factory: Callable[[], Any],
) -> None:
    """Compatibility wrapper for extracted processing-run finalization."""
    stats.finalize_stats_run(
        stats_run, result, team_result, group_result, channels_deleted_count, db_factory
    )

def _refresh_m3u_accounts(db_factory: Callable[[], Any], dispatcharr_client: Any) -> dict:
    """Compatibility wrapper for the extracted M3U refresh helper."""
    return preparation.refresh_m3u_accounts_for_groups(db_factory, dispatcharr_client)


def _validate_channel_ranges(
    db_factory: Callable[[], Any],
    external_occupied: set[int],
) -> dict:
    """Compatibility wrapper for extracted channel-range validation."""
    return processing.validate_channel_ranges(db_factory, external_occupied)


def _sync_global_channels(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
    update_progress: Callable,
    external_occupied: set[int] | None = None,
) -> bool:
    """Compatibility wrapper for extracted global channel reassignment."""
    return channel_output.reassign_global_channels(
        db_factory, dispatcharr_client, update_progress, external_occupied
    )



def run_stream_ordering_only(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
    manual: bool = True,
) -> dict | None:
    """Re-sort every managed channel's streams without a generation run (#576).

    The whole ordering step and nothing else: pull current stats from
    Dispatcharr, re-apply the rules, push only the channels whose order
    changed. No matching, no provider calls, no EPG rebuild, no media-server
    refresh, no run-history row. Takes the generation lock so it can never
    overlap a real run (or vice versa); returns None when a run is in
    progress so the caller can answer 409.

    ``manual`` defaults True: this is the user's button, and like a manual
    generation it bypasses the live-event #1 pin (#232) — the escape hatch
    when the pinned stream is wrong. A scheduled caller must pass False.
    """
    global _generation_running

    if not _generation_lock.acquire(blocking=False):
        return None
    if _generation_running:
        _generation_lock.release()
        return None
    _generation_running = True
    try:
        logger.info("[ORDERING] Manual stream re-order (no generation)")
        return _apply_stream_ordering(
            db_factory, dispatcharr_client, lambda *a, **k: None, manual=manual
        )
    finally:
        _generation_running = False
        _generation_lock.release()



def _apply_stream_ordering(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
    update_progress: Callable,
    manual: bool = False,
) -> dict:
    """Compatibility wrapper injecting the facade ChannelManager."""
    return channel_steps.apply_stream_ordering(
        db_factory,
        dispatcharr_client,
        update_progress,
        manual,
        channel_manager_factory=ChannelManager,
    )


def _run_stream_audit(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
) -> None:
    """Compatibility wrapper injecting the facade ChannelManager."""
    channel_steps.run_stream_audit(
        db_factory, dispatcharr_client, channel_manager_factory=ChannelManager
    )
