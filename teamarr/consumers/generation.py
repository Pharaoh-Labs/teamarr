"""Unified EPG generation workflow.

This module provides the single source of truth for EPG generation.
Both the streaming API endpoint and the background scheduler call this.
"""

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import as_completed
from typing import Any

from teamarr.channelsdvr.client import ChannelsDVRClient
from teamarr.consumers.generation_pipeline import channel_steps
from teamarr.consumers.generation_pipeline.models import (
    CallbackCancellationToken,
    GenerationCancelled,
    GenerationContext,
    GenerationResult,
    GenerationSettingsSnapshot,
    ProgressCallback,
    legacy_progress_reporter,
)
from teamarr.consumers.generation_pipeline.phases import channel_output, preparation, processing
from teamarr.consumers.generation_pipeline.runner import GenerationStage, StageRunner
from teamarr.dispatcharr import EPGManager
from teamarr.dispatcharr.factory import DispatcharrConnection
from teamarr.dispatcharr.managers import ChannelManager
from teamarr.emby.client import EmbyClient
from teamarr.jellyfin.client import JellyfinClient
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

# Guide refreshes can take minutes. Keep batches serialized without holding the
# generation lock so a new EPG run can complete while an older guide refresh runs.
_media_refresh_lock = threading.Lock()


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
    from teamarr.consumers import create_lifecycle_service

    context.lifecycle_service = create_lifecycle_service(
        context.db_factory, context.sports_service, dispatcharr_client=context.dispatcharr_client
    )
    context.lifecycle_service.compute_external_occupied()
    context.lifecycle_service.sync_stream_profiles()


def _stage_dispatcharr_epg(context: GenerationContext) -> None:
    from teamarr.consumers.generation_status import is_cancellation_requested

    if not (context.dispatcharr_client and context.settings.dispatcharr.epg_id):
        return
    assert context.lifecycle_service is not None
    assert context.team_channel_manager is not None
    context.report("dispatcharr", 96, "Refreshing Dispatcharr EPG...")
    raw_client = (
        context.dispatcharr_client.client
        if isinstance(context.dispatcharr_client, DispatcharrConnection)
        else context.dispatcharr_client
    )
    refresh = EPGManager(raw_client).wait_for_refresh(
        context.settings.dispatcharr.epg_id,
        timeout=300,
        cancellation_check=is_cancellation_requested,
    )
    context.result.epg_refresh = {
        "success": refresh.success,
        "message": refresh.message,
        "duration": refresh.duration,
    }
    context.report("dispatcharr", 97, "Associating EPG with channels...")
    context.result.epg_association = context.lifecycle_service.associate_epg_with_channels(
        context.settings.dispatcharr.epg_id
    )
    try:
        context.result.epg_association["managed_team_channels"] = (
            context.team_channel_manager.associate_epg(context.settings.dispatcharr.epg_id)
        )
    except Exception as exc:  # noqa: BLE001 - per-step isolation
        logger.exception("[GENERATION] Managed team EPG association failed: %s", exc)


def _stage_media_jobs(context: GenerationContext) -> None:
    context.media_jobs = _get_media_refresh_jobs(context.db_factory)
    if context.media_jobs and _dry_run_media_refresh(context.result, context.media_jobs):
        context.media_jobs = []


def _stage_deletions(context: GenerationContext) -> None:
    assert context.lifecycle_service is not None
    context.report("lifecycle", 98, "Processing scheduled deletions...")
    try:
        deletion_result = context.lifecycle_service.process_scheduled_deletions()
        context.channels_deleted_count = len(deletion_result.deleted)
        context.result.deletions = {
            "deleted_count": context.channels_deleted_count,
            "error_count": len(deletion_result.errors),
        }
        if deletion_result.deleted:
            logger.info(
                "[GENERATION] Deleted %d expired channel(s)", context.channels_deleted_count
            )
    except Exception as exc:
        logger.warning("[GENERATION] Scheduled deletions failed: %s", exc)
        context.result.deletions = {"error": str(exc)}


def _stage_reconciliation(context: GenerationContext) -> None:
    from teamarr.consumers import create_reconciler
    from teamarr.database.channels import get_reconciliation_settings

    context.report("reconciliation", 99, "Running reconciliation...")
    try:
        with context.db_factory() as conn:
            settings = get_reconciliation_settings(conn)
        if settings.get("reconcile_on_epg_generation", True):
            reconciliation = create_reconciler(
                context.db_factory, context.dispatcharr_client
            ).reconcile(auto_fix=False)
            context.result.reconciliation = reconciliation.summary
            if reconciliation.issues_found:
                logger.info("[RECONCILE] Found %d issue(s)", len(reconciliation.issues_found))
    except Exception as exc:
        logger.warning("[RECONCILE] Failed: %s", exc)
        context.result.reconciliation = {"error": str(exc)}


def _stage_stream_audit(context: GenerationContext) -> None:
    from teamarr.consumers import detect_stale_groups

    try:
        detect_stale_groups(context.db_factory)
    except Exception as exc:
        logger.warning("[STALE_GROUPS] Detection failed: %s", exc)
    try:
        _run_stream_audit(context.db_factory, context.dispatcharr_client)
    except Exception as exc:
        logger.warning("[STREAM_AUDIT] Post-generation audit failed: %s", exc)


def _stage_cleanup(context: GenerationContext) -> None:
    context.report("cleanup", 99, "Cleaning up history...")
    results = _run_cleanup_tasks(context.db_factory, context.dispatcharr_client, context.report)
    context.result.cleanup = results["history"]
    context.result.logo_cleanup = results["logos"]


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
    """Snapshot enabled media servers for the post-generation refresh batch."""
    from teamarr.database.settings import (
        get_channelsdvr_settings,
        get_emby_settings,
        get_jellyfin_settings,
    )

    try:
        with db_factory() as conn:
            emby_settings = get_emby_settings(conn)
            jellyfin_settings = get_jellyfin_settings(conn)
            channelsdvr_settings = get_channelsdvr_settings(conn)
    except Exception as exc:
        logger.warning("[MEDIA_SERVERS] Could not load refresh settings: %s", exc)
        return []

    jobs: list[tuple[str, Any]] = []
    if emby_settings.enabled:
        jobs.extend(("emby", server) for server in emby_settings.servers if server.url)
    if jellyfin_settings.enabled:
        jobs.extend(("jellyfin", server) for server in jellyfin_settings.servers if server.url)
    if channelsdvr_settings.enabled:
        jobs.extend(
            ("channelsdvr", server) for server in channelsdvr_settings.servers if server.url
        )
    return jobs


def _start_media_server_refresh(
    db_factory: Callable[[], Any], run_id: int, jobs: list[tuple[str, Any]]
) -> None:
    """Run a guide refresh batch after generation completion.

    Batches wait for one another so a server never receives overlapping guide
    refreshes, but this worker never blocks the next generation's core work.
    """

    def run() -> None:
        with _media_refresh_lock:
            started_at = time.time()
            try:
                from teamarr.consumers.media_refresh_status import (
                    complete_refresh,
                    start_refresh,
                    update_refresh,
                )

                start_refresh(len(jobs))
                outcomes = _run_media_server_refreshes(
                    jobs,
                    lambda phase, _percent, _message, *_: update_refresh(
                        f"Refreshing {_media_refresh_title(phase)} guide..."
                    ),
                    lambda: False,
                    lambda current, _total: update_refresh("Refreshing media servers...", current),
                )
                flattened = [
                    _media_server_outcome(kind, label, outcome) for kind, label, outcome in outcomes
                ]
                complete_refresh(flattened)
            except Exception as exc:  # noqa: BLE001 - detached worker must not escape
                logger.exception("[MEDIA_SERVERS] Background refresh failed")
                from teamarr.consumers.media_refresh_status import fail_refresh

                fail_refresh(str(exc))
                flattened = [
                    {
                        "kind": kind,
                        "server": getattr(server, "name", None) or getattr(server, "url", ""),
                        "success": False,
                        "duration": 0.0,
                        "error": str(exc),
                    }
                    for kind, server in jobs
                ]

            _save_media_refresh_outcomes(
                db_factory, run_id, flattened, round(time.time() - started_at, 2)
            )

    threading.Thread(target=run, daemon=True, name=f"media-refresh-{run_id}").start()


def _media_refresh_title(kind: str) -> str:
    """Return a user-facing integration name without exposing server details."""
    return {"emby": "Emby", "jellyfin": "Jellyfin", "channelsdvr": "Channels DVR"}.get(
        kind, "media server"
    )


def _save_media_refresh_outcomes(
    db_factory: Callable[[], Any], run_id: int, outcomes: list[dict], duration: float
) -> None:
    """Attach detached refresh outcomes to the EPG run that scheduled them."""
    from teamarr.database.stats import get_run, save_run

    try:
        with db_factory() as conn:
            run = get_run(conn, run_id)
            if run is None:
                logger.warning(
                    "[MEDIA_SERVERS] Run %d disappeared before refresh completed", run_id
                )
                return
            run.extra_metrics["media_servers"] = outcomes
            run.extra_metrics.setdefault("phase_timings", {})["media_server_refresh"] = duration
            save_run(conn, run)
    except Exception as exc:  # noqa: BLE001 - guide refresh must never affect generation
        logger.exception("[MEDIA_SERVERS] Could not save background refresh outcomes: %s", exc)


def _dry_run_media_refresh(result: Any, jobs: list[tuple[str, Any]]) -> bool:
    """DRY_RUN (#554): record what would have been refreshed, run nothing.

    Returns True when dry-run is active (caller skips the refresh jobs).
    """
    from teamarr.config.runtime import dry_run

    if not dry_run():
        return False
    by_kind: dict[str, list[str]] = {}
    for kind, server in jobs:
        by_kind.setdefault(kind, []).append(getattr(server, "url", None) or str(server))
    for kind, urls in by_kind.items():
        logger.info("[DRY_RUN] Suppressed %s guide refresh for %s", kind, ", ".join(urls))
        payload = {"success": True, "dry_run": True, "servers": urls}
        result.media_server_outcomes += [
            {
                "kind": kind,
                "server": u,
                "success": True,
                "duration": 0.0,
                "error": None,
                "dry_run": True,
            }
            for u in urls
        ]
        if kind == "emby":
            result.emby_refresh = payload
        elif kind == "jellyfin":
            result.jellyfin_refresh = payload
        elif kind == "channelsdvr":
            result.channelsdvr_refresh = payload
            result.channelsdvr_epg_refresh = dict(payload)
    return True


def _run_media_server_refreshes(
    jobs: list[tuple[str, Any]],
    update_progress: Callable[..., None],
    is_cancellation_requested: Callable[[], bool],
    completion_callback: Callable[[int, int], None] | None = None,
) -> list[tuple[str, str, dict]]:
    """Run every media-server refresh job concurrently (#471).

    Each job is (kind, server) with kind in emby/jellyfin/channelsdvr.
    Returns (kind, label, outcome) triples where outcome carries "guide"
    (Emby/Jellyfin) or "m3u"/"epg" (Channels DVR) result dicts. A job that
    raises yields a failed "guide" outcome — never an exception.
    """
    from concurrent.futures import ThreadPoolExecutor

    results: list[tuple[str, str, dict]] = []
    with ThreadPoolExecutor(
        max_workers=min(8, len(jobs)), thread_name_prefix="media-refresh"
    ) as pool:
        futures = {
            pool.submit(
                _refresh_one_media_server,
                kind,
                server,
                update_progress,
                is_cancellation_requested,
            ): (kind, server)
            for kind, server in jobs
        }
        for completed, future in enumerate(as_completed(futures), start=1):
            kind, server = futures[future]
            label = server.name or server.url or ""
            try:
                results.append((kind, label, future.result()))
            except Exception as e:  # noqa: BLE001 — per-server isolation
                logger.warning(
                    "[%s] %s: refresh failed (non-blocking): %s",
                    kind.upper(),
                    label,
                    e,
                )
                results.append((kind, label, {"guide": {"success": False, "error": str(e)}}))
            if completion_callback:
                completion_callback(completed, len(jobs))
    return results


def _media_server_outcome(kind: str, label: str, outcome: dict) -> dict:
    """Flatten one server's refresh result for the run row (#649).

    Channels DVR has two steps (m3u + epg); it counts as a success only when
    both did, and reports the first error.
    """
    parts = [v for v in (outcome.get("guide"), outcome.get("m3u"), outcome.get("epg")) if v]
    errors = [p.get("error") or p.get("message") for p in parts if not p.get("success")]
    return {
        "kind": kind,
        "server": label,
        "success": bool(parts) and all(p.get("success") for p in parts),
        "duration": round(sum(float(p.get("duration") or 0) for p in parts), 2),
        "error": errors[0] if errors else None,
    }


def _refresh_one_media_server(
    kind: str,
    server: Any,
    update_progress: Callable[..., None],
    is_cancellation_requested: Callable[[], bool],
) -> dict:
    """Refresh a single media server (runs on a worker thread)."""
    label = server.name or server.url or ""

    if kind == "channelsdvr":
        m3u_res, epg_res = _refresh_channelsdvr_server(
            server,
            label,
            lambda msg: update_progress("channelsdvr", 97, f"{msg} ({label})"),
        )
        return {"m3u": m3u_res, "epg": epg_res}

    title = "Emby" if kind == "emby" else "Jellyfin"
    client_cls = EmbyClient if kind == "emby" else JellyfinClient
    client = client_cls(
        base_url=server.url,
        username=server.username or "",
        password=server.password or "",
        api_key=server.api_key,
    )

    update_progress(kind, 97, f"Refreshing {title} guide... ({label})")

    def on_progress(pct):
        update_progress(kind, 97, f"Refreshing {title} guide... ({label}) {pct:.0f}%")

    guide_result = client.trigger_guide_refresh(
        timeout=300,
        on_progress=on_progress,
        cancellation_check=is_cancellation_requested,
    )
    if guide_result.get("success"):
        logger.info(
            "[%s] %s: guide refresh completed in %.1fs",
            kind.upper(),
            label,
            guide_result.get("duration", 0),
        )
    else:
        logger.warning(
            "[%s] %s: guide refresh failed: %s",
            kind.upper(),
            label,
            guide_result.get("message"),
        )
    return {"guide": guide_result}


def _refresh_channelsdvr_server(
    server: Any,
    label: str,
    progress: Callable[[str], None],
) -> tuple[dict | None, dict | None]:
    """Refresh one Channels DVR server's M3U source, then its XMLTV lineup.

    Sequences the two refreshes on real evidence: waits for the M3U
    channel-list refresh to actually finish before firing the guide PUT,
    so the guide doesn't index against a stale channel list. Both waits
    poll CDVR /log (see client docs).

    Returns (m3u_result, epg_result); either is None when that phase
    didn't run (no source / no lineup configured).
    """
    # The client derives lineup_id as "XMLTV-<source_name>" when no lineup
    # is explicitly configured, so the guide refresh fires even if the
    # user only set the M3U source.
    client = ChannelsDVRClient(
        base_url=server.url,
        source_name=server.source_name or "",
        lineup_id=server.lineup_id or "",
    )

    if not (client.source_name or client.lineup_id):
        logger.warning(
            "[CHANNELSDVR] %s: enabled but no source name or XMLTV lineup "
            "configured — nothing to refresh. Set a source name "
            "(and optionally a lineup) in Settings.",
            label,
        )
        return None, None

    m3u_result: dict | None = None
    if client.source_name:
        progress("Refreshing Channels DVR channels...")
        m3u_result = client.trigger_m3u_refresh(
            timeout=60, wait_for_completion=bool(client.lineup_id)
        )
        if m3u_result.get("success"):
            logger.info(
                "[CHANNELSDVR] %s: M3U refresh triggered in %.1fs (completion: %s)",
                label,
                m3u_result.get("duration", 0),
                m3u_result.get("completed", "not awaited"),
            )
        else:
            logger.warning(
                "[CHANNELSDVR] %s: M3U refresh failed: %s",
                label,
                m3u_result.get("message"),
            )

    epg_result: dict | None = None
    if client.lineup_id:
        if client.lineup_derived:
            logger.info(
                "[CHANNELSDVR] %s: no XMLTV lineup configured; derived '%s' from source '%s'",
                label,
                client.lineup_id,
                client.source_name,
            )
        progress("Refreshing Channels DVR guide...")
        epg_result = client.trigger_epg_refresh(timeout=60, verify=True)
        if not epg_result.get("success"):
            logger.warning(
                "[CHANNELSDVR] %s: EPG refresh failed: %s",
                label,
                epg_result.get("message"),
            )
        else:
            verification = epg_result.get("verification") or {}
            status = verification.get("status")
            if status == "no_fetch":
                logger.warning(
                    "[CHANNELSDVR] %s: EPG refresh accepted but guide '%s' "
                    "was not re-fetched — guide may be stale",
                    label,
                    client.lineup_id,
                )
            else:
                logger.info(
                    "[CHANNELSDVR] %s: EPG refresh for lineup '%s' in %.1fs (verification: %s)",
                    label,
                    client.lineup_id,
                    epg_result.get("duration", 0),
                    status or "not verified",
                )
    else:
        logger.warning(
            "[CHANNELSDVR] %s: skipping EPG/guide refresh: no XMLTV lineup "
            "configured and none could be derived (set a source name so the "
            "lineup can be inferred). The guide will stay stale until "
            "refreshed manually.",
            label,
        )

    return m3u_result, epg_result


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

def _run_cleanup_tasks(
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


def _finalize_stats_run(
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
