"""Cleanup and run-statistics work for the generation pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from teamarr.utilities import call_metrics

if TYPE_CHECKING:  # pragma: no cover - typing only
    from teamarr.consumers.generation_pipeline.models import GenerationContext, GenerationResult

logger = logging.getLogger("teamarr.consumers.generation")


def stage_cleanup(
    context: GenerationContext,
    cleanup_tasks: Callable[[Callable[[], Any], Any, Callable], dict],
) -> None:
    """Run cleanup and retain its result fields on the generation result."""
    context.report("cleanup", 99, "Cleaning up history...")
    results = cleanup_tasks(context.db_factory, context.dispatcharr_client, context.report)
    context.result.cleanup = results["history"]
    context.result.logo_cleanup = results["logos"]


def run_cleanup_tasks(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
    update_progress: Callable,
) -> dict:
    """Run all post-generation cleanup: history, old runs, unused logos."""
    from teamarr.database.channels import cleanup_old_history, get_reconciliation_settings

    results: dict = {"history": {}, "logos": {}}

    # History cleanup
    try:
        with db_factory() as conn:
            cleanup_settings = get_reconciliation_settings(conn)
            retention_days = cleanup_settings.get("channel_history_retention_days", 90)
            deleted_count = cleanup_old_history(conn, retention_days)
            results["history"] = {"deleted_count": deleted_count}
            if deleted_count > 0:
                logger.info("[CLEANUP] Removed %d old history record(s)", deleted_count)
    except Exception as e:
        logger.warning("[CLEANUP] History cleanup failed: %s", e)
        results["history"] = {"error": str(e)}

    # Old processing runs (>30 days)
    try:
        from teamarr.database.stats import cleanup_old_runs

        with db_factory() as conn:
            runs_deleted = cleanup_old_runs(conn, days=30)
            if runs_deleted > 0:
                logger.info("[CLEANUP] Removed %d old processing run(s)", runs_deleted)
    except Exception as e:
        logger.warning("[CLEANUP] Run history cleanup failed: %s", e)

    # Unused logos
    try:
        from teamarr.database.settings import get_dispatcharr_settings

        with db_factory() as conn:
            dispatcharr_settings = get_dispatcharr_settings(conn)
        if dispatcharr_settings.cleanup_unused_logos and dispatcharr_client:
            update_progress("cleanup", 99, "Cleaning up unused logos...")
            cleanup_result = dispatcharr_client.logos.cleanup_unused()
            if cleanup_result.success:
                logos_deleted = (
                    cleanup_result.data.get("deleted_count", 0) if cleanup_result.data else 0
                )
                results["logos"] = {"deleted_count": logos_deleted}
                if logos_deleted > 0:
                    logger.info("[CLEANUP] Removed %d unused logo(s)", logos_deleted)
            else:
                logger.warning("[CLEANUP] Logo cleanup failed: %s", cleanup_result.error)
                results["logos"] = {"error": cleanup_result.error}
    except Exception as e:
        logger.warning("[CLEANUP] Logo cleanup failed: %s", e)
        results["logos"] = {"error": str(e)}

    return results

def finalize_stats_run(
    stats_run: Any,
    result: GenerationResult,
    team_result: Any,
    group_result: Any,
    channels_deleted_count: int,
    db_factory: Callable[[], Any],
) -> None:
    """Populate stats run with generation results and save to database."""
    from teamarr.database.channels import get_all_managed_channels
    from teamarr.database.stats import save_run

    stats_run.programmes_total = result.programmes_total
    stats_run.programmes_events = team_result.total_events + group_result.total_events
    stats_run.programmes_pregame = team_result.total_pregame + group_result.total_pregame
    stats_run.programmes_postgame = team_result.total_postgame + group_result.total_postgame
    stats_run.programmes_idle = team_result.total_idle
    stats_run.channels_created = group_result.total_channels_created
    stats_run.channels_updated = group_result.total_channels_updated
    stats_run.channels_skipped = group_result.total_channels_skipped
    stats_run.channels_errors = group_result.total_channel_errors
    stats_run.channels_deleted = channels_deleted_count + group_result.total_channels_deleted
    stats_run.xmltv_size_bytes = result.file_size
    stats_run.streams_fetched = group_result.total_streams_fetched
    stats_run.streams_matched = group_result.total_streams_matched
    stats_run.streams_unmatched = group_result.total_streams_unmatched
    stats_run.streams_cached = group_result.total_streams_cached
    stats_run.extra_metrics["teams_processed"] = result.teams_processed
    stats_run.extra_metrics["groups_processed"] = result.groups_processed
    # Per-group breakdown (#645): replaces the old one-row-per-group sub-runs.
    stats_run.extra_metrics["groups"] = group_result.group_summaries()
    stats_run.extra_metrics["file_written"] = result.file_written

    # Post-processing enforcement outcomes (iua3.7): one record per step with
    # ok/count/error, so a silently failing enforcement step shows up in the
    # run summary instead of only in warning logs.
    if getattr(group_result, "enforcement", None):
        stats_run.extra_metrics["enforcement"] = [
            step.to_dict() for step in group_result.enforcement
        ]

    # Provider HTTP call volume for this run (kbbk). The per-endpoint breakdown
    # and total let the run summary surface calls-per-channel, making a
    # call-volume regression (the #254 refetch bug class) visible. Snapshot the
    # run-scoped counter that was reset at run start.

    stats_run.extra_metrics["provider_calls"] = call_metrics.snapshot()
    stats_run.extra_metrics["provider_calls_total"] = call_metrics.total()

    # Media-server refresh outcomes (#649): non-blocking failures otherwise
    # leave no trace beyond a phase timing collapsing to ~0.
    if result.media_server_outcomes:
        stats_run.extra_metrics["media_servers"] = list(result.media_server_outcomes)

    # Per-phase wall time so run-to-run comparisons (and perf regressions)
    # are visible in the run summary instead of requiring log archaeology.
    if result.phase_timings:
        stats_run.extra_metrics["phase_timings"] = dict(result.phase_timings)

    with db_factory() as conn:
        active_channels = get_all_managed_channels(conn, include_deleted=False)
        stats_run.channels_active = len(active_channels)
        logger.info("[GENERATION] %d active managed channels", len(active_channels))

    stats_run.complete(status="completed")

    with db_factory() as conn:
        save_run(conn, stats_run)
