"""Unified EPG generation workflow.

This module provides the single source of truth for EPG generation.
Both the streaming API endpoint and the background scheduler call this.
"""

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from teamarr.channelsdvr.client import ChannelsDVRClient
from teamarr.dispatcharr import EPGManager, M3UManager
from teamarr.dispatcharr.factory import DispatcharrConnection
from teamarr.dispatcharr.managers import ChannelManager
from teamarr.emby.client import EmbyClient
from teamarr.jellyfin.client import JellyfinClient
from teamarr.services import create_default_service
from teamarr.services.sports_data import flush_shared_cache
from teamarr.services.stream_ordering import StreamOrderingService
from teamarr.utilities import call_metrics
from teamarr.utilities.xmltv import merge_xmltv_content

logger = logging.getLogger(__name__)


class GenerationCancelled(Exception):
    """Raised when a generation run is cancelled by the user."""


# Global lock to prevent concurrent EPG generation runs
_generation_lock = threading.Lock()
_generation_running = False


@dataclass
class GenerationResult:
    """Result of a full EPG generation run."""

    success: bool = True
    error: str | None = None

    # Timing
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_seconds: float = 0.0

    # EPG stats
    teams_processed: int = 0
    teams_programmes: int = 0
    groups_processed: int = 0
    groups_programmes: int = 0
    programmes_total: int = 0

    # File output
    file_written: bool = False
    file_path: str | None = None
    file_size: int = 0

    # Sub-task results
    m3u_refresh: dict = field(default_factory=dict)
    stream_ordering: dict = field(default_factory=dict)
    epg_refresh: dict = field(default_factory=dict)
    epg_association: dict = field(default_factory=dict)
    deletions: dict = field(default_factory=dict)
    reconciliation: dict = field(default_factory=dict)
    cleanup: dict = field(default_factory=dict)
    logo_cleanup: dict = field(default_factory=dict)
    channel_conflicts: dict = field(default_factory=dict)
    emby_refresh: dict = field(default_factory=dict)
    jellyfin_refresh: dict = field(default_factory=dict)
    channelsdvr_refresh: dict = field(default_factory=dict)
    channelsdvr_epg_refresh: dict = field(default_factory=dict)

    # For stats run tracking
    run_id: int | None = None


# Type alias for progress callback
# (phase: str, percent: int, message: str, current: int, total: int, item_name: str) -> None
ProgressCallback = Callable[[str, int, str, int, int, str], None]


def run_full_generation(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None = None,
    progress_callback: ProgressCallback | None = None,
) -> GenerationResult:
    """Run the complete EPG generation workflow.

    This is the single source of truth for EPG generation. Both the
    streaming API endpoint and the background scheduler call this function.

    Workflow:
    1. Refresh M3U accounts (0-5%)
    2. Process all teams (5-50%) - 45% budget
    3. Process all event groups (50-95%) - 45% budget
    4. Merge and save XMLTV (95-96%)
    5. Dispatcharr EPG refresh + channel association (96-98%)
    6. Process scheduled deletions (98-99%)
    7. Run reconciliation + cleanup (99-100%)

    Args:
        db_factory: Factory function returning database connection context manager
        dispatcharr_client: Optional DispatcharrClient for Dispatcharr operations
        progress_callback: Optional callback for progress updates

    Returns:
        GenerationResult with all stats and sub-task results
    """
    global _generation_running

    # Prevent concurrent generation runs
    if not _generation_lock.acquire(blocking=False):
        logger.warning("[GENERATION] Already in progress, skipping duplicate run")
        result = GenerationResult()
        result.success = False
        result.error = "Generation already in progress"
        return result

    if _generation_running:
        _generation_lock.release()
        logger.warning("[GENERATION] Already in progress (flag check), skipping")
        result = GenerationResult()
        result.success = False
        result.error = "Generation already in progress"
        return result

    _generation_running = True

    from teamarr.consumers import (
        create_lifecycle_service,
        create_reconciler,
        detect_stale_groups,
        process_all_event_groups,
        process_all_teams,
    )
    from teamarr.consumers.team_processor import get_all_team_xmltv
    from teamarr.database.channels import get_reconciliation_settings
    from teamarr.database.groups import get_all_group_xmltv
    from teamarr.database.settings import (
        get_dispatcharr_settings,
        get_display_settings,
        get_epg_settings,
    )
    from teamarr.database.stats import create_run

    result = GenerationResult()
    result.started_at = time.time()

    def update_progress(
        phase: str,
        percent: int,
        message: str,
        current: int = 0,
        total: int = 0,
        item_name: str = "",
    ):
        if progress_callback:
            progress_callback(phase, percent, message, current, total, item_name)

    # Create stats run for tracking with database-level lock
    # Use BEGIN IMMEDIATE to acquire exclusive write lock BEFORE checking
    # This prevents race conditions where two processes both pass the check
    # before either has inserted their row
    with db_factory() as conn:
        try:
            # BEGIN IMMEDIATE acquires write lock immediately, blocking other writers
            conn.execute("BEGIN IMMEDIATE")

            # Now check for in-progress runs - with lock held, this is reliable
            recent_running = conn.execute("""
                SELECT id FROM processing_runs
                WHERE run_type = 'full_epg'
                  AND status = 'running'
                  AND started_at > datetime('now', '-5 minutes')
                LIMIT 1
            """).fetchone()

            if recent_running:
                conn.execute("ROLLBACK")
                _generation_running = False
                _generation_lock.release()
                logger.warning(
                    "[GENERATION] Already in progress (run %d), skipping", recent_running["id"]
                )
                result = GenerationResult()
                result.success = False
                result.error = "Generation already in progress"
                return result

            # No running jobs - create our run (still holding lock)
            stats_run = create_run(conn, run_type="full_epg")
            result.run_id = stats_run.id
            # create_run commits, which releases the lock

        except Exception as e:
            try:
                conn.execute("ROLLBACK")
            except Exception as rollback_err:
                logger.debug(
                    "[GENERATION] Rollback failed during lock acquisition: %s", rollback_err
                )
            _generation_running = False
            _generation_lock.release()
            logger.error("[GENERATION] Failed to acquire lock: %s", e)
            result = GenerationResult()
            result.success = False
            result.error = f"Failed to acquire lock: {e}"
            return result

    # Import cancellation helpers
    from teamarr.consumers.generation_status import cancel_generation, is_cancellation_requested

    def check_cancelled():
        """Check if cancellation was requested and raise if so."""
        if is_cancellation_requested():
            raise GenerationCancelled("Cancelled by user")

    try:
        # Increment generation counter ONCE at start of full EPG run
        # This ensures all groups in this run share the same generation
        from teamarr.consumers.stream_match_cache import increment_generation_counter

        current_generation = increment_generation_counter(db_factory)
        logger.info("[GENERATION] Starting with cache generation %d", current_generation)

        # Reset the run-scoped provider-call counter so this run's totals start
        # clean. Runs are serialized (duplicate runs are rejected above), so a
        # single process-global counter is safe. Snapshot is persisted at run end.

        call_metrics.reset()

        # Create a single SportsDataService instance to share across all processing
        # This ensures the event cache stays warm throughout the entire run
        # (Previously each consumer created its own service with a cold cache)
        shared_service = create_default_service()

        # Get settings
        with db_factory() as conn:
            settings = get_epg_settings(conn)
            dispatcharr_settings = get_dispatcharr_settings(conn)
            display_settings = get_display_settings(conn)

        # Step 1: Refresh M3U accounts (0-5%)
        check_cancelled()
        update_progress("init", 3, "Refreshing M3U accounts...")
        if dispatcharr_client:
            result.m3u_refresh = _refresh_m3u_accounts(db_factory, dispatcharr_client)

        # Step 2: Process all teams (5-50%) - 45% budget
        check_cancelled()
        update_progress("teams", 5, "Processing teams...")

        teams_start_time = time.time()

        def team_progress(current: int, total: int, name: str):
            # Maps 0-100% within teams to 5-50% overall
            pct = 5 + int((current / total) * 45) if total > 0 else 5
            elapsed = time.time() - teams_start_time
            remaining = total - current

            # Messages from team_processor already include context
            # (Processing X..., Finished X, now processing: Y, Z)
            # Just add timing and counts
            if remaining > 0:
                msg = f"{name} ({current}/{total}) - {remaining} remaining [{elapsed:.1f}s]"
            else:
                msg = f"{name} ({current}/{total}) [{elapsed:.1f}s]"
            update_progress("teams", pct, msg, current, total, name)

        team_result = process_all_teams(db_factory=db_factory, progress_callback=team_progress)
        result.teams_processed = team_result.teams_processed
        result.teams_programmes = team_result.total_programmes

        # Transition message - teams done, starting groups
        logger.info("[GENERATION] Sending transition message: teams -> groups")
        update_progress(
            "groups",
            50,
            f"Teams complete ({result.teams_processed} processed), loading event groups...",
            0,
            1,
            "Loading event groups...",
        )
        logger.info("[GENERATION] Transition message sent")

        # Step 3: Process all event groups (50-95%) - 45% budget
        check_cancelled()

        groups_start_time = time.time()

        def group_progress(current: int, total: int, name: str):
            # Maps 0-100% within groups to 50-95% overall
            pct = 50 + int((current / total) * 45) if total > 0 else 50
            elapsed = time.time() - groups_start_time

            # Check if this is a stream-level progress update (contains ✓ or ✗)
            if "✓" in name or "✗" in name:
                # Stream-level progress - name contains "GroupName: StreamName ✓/✗ (x/y)"
                # Pass the full message as item_name for display in toast
                update_progress("groups", pct, name, current, total, name)
            else:
                # Group completion - add context
                remaining = total - current
                if remaining > 0:
                    msg = f"Finished {name} ({current}/{total}) - {remaining} remaining [{elapsed:.1f}s]"  # noqa: E501
                else:
                    msg = f"Finished {name} ({current}/{total}) [{elapsed:.1f}s]"
                update_progress("groups", pct, msg, current, total, name)

        # Compute external occupied channel numbers once for the entire run (#146)
        # This prevents Teamarr from assigning numbers already used by non-Teamarr channels
        from teamarr.consumers.lifecycle import compute_external_occupied

        _channel_mgr = (
            dispatcharr_client.channels
            if isinstance(dispatcharr_client, DispatcharrConnection)
            else None
        )
        external_occupied = compute_external_occupied(db_factory, _channel_mgr)

        # Pre-generation validation: detect channel range conflicts (#146)
        if external_occupied:
            result.channel_conflicts = _validate_channel_ranges(
                db_factory, external_occupied
            )

        group_result = process_all_event_groups(
            db_factory=db_factory,
            dispatcharr_client=dispatcharr_client,
            progress_callback=group_progress,
            generation=current_generation,  # Share generation across all groups
            service=shared_service,  # Reuse service to maintain warm cache
        )
        result.groups_processed = group_result.groups_processed
        result.groups_programmes = group_result.total_programmes
        result.programmes_total = result.teams_programmes + result.groups_programmes

        # Step 3b: Global channel reassignment (if enabled)
        check_cancelled()
        _sync_global_channels(
            db_factory, dispatcharr_client, update_progress,
            external_occupied=external_occupied,
        )

        # Step 3b: Apply stream ordering rules to all channels (93-95%)
        check_cancelled()
        update_progress("ordering", 93, "Applying stream ordering rules...")
        result.stream_ordering = _apply_stream_ordering(
            db_factory, dispatcharr_client, update_progress
        )

        # Step 4: Merge and save XMLTV (95-96%)
        check_cancelled()
        update_progress("saving", 95, "Saving XMLTV...")

        xmltv_contents: list[str] = []
        with db_factory() as conn:
            team_xmltv = get_all_team_xmltv(conn)
            xmltv_contents.extend(team_xmltv)
            group_xmltv = get_all_group_xmltv(conn)
            xmltv_contents.extend(group_xmltv)

        output_path = settings.epg_output_path
        if xmltv_contents and output_path:
            merged_xmltv = merge_xmltv_content(
                xmltv_contents,
                generator_name=display_settings.xmltv_generator_name,
                generator_url=display_settings.xmltv_generator_url,
            )
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(merged_xmltv, encoding="utf-8")
            result.file_written = True
            result.file_path = str(output_file.absolute())
            result.file_size = len(merged_xmltv)
            logger.info(
                "[GENERATION] EPG written to %s (%s bytes)", output_path, f"{result.file_size:,}"
            )

        # Create lifecycle service once for steps 5-6
        # Reuse shared_service to maintain cache warmth
        lifecycle_service = create_lifecycle_service(
            db_factory,
            shared_service,
            dispatcharr_client=dispatcharr_client,
        )
        # Compute external channel numbers to avoid collisions (#146)
        lifecycle_service.compute_external_occupied()

        # Step 5: Dispatcharr EPG refresh + channel association (96-98%)
        check_cancelled()
        if dispatcharr_client and dispatcharr_settings.epg_id:
            update_progress("dispatcharr", 96, "Refreshing Dispatcharr EPG...")

            raw_client = (
                dispatcharr_client.client
                if isinstance(dispatcharr_client, DispatcharrConnection)
                else dispatcharr_client
            )
            epg_manager = EPGManager(raw_client)
            refresh_result = epg_manager.wait_for_refresh(
                dispatcharr_settings.epg_id,
                timeout=300,
                cancellation_check=is_cancellation_requested,
            )
            result.epg_refresh = {
                "success": refresh_result.success,
                "message": refresh_result.message,
                "duration": refresh_result.duration,
            }

            update_progress("dispatcharr", 97, "Associating EPG with channels...")
            result.epg_association = lifecycle_service.associate_epg_with_channels(
                dispatcharr_settings.epg_id
            )

        # Step 5b: Emby Live TV guide refresh
        check_cancelled()
        try:
            from teamarr.database.settings import get_emby_settings

            with db_factory() as conn:
                emby_settings = get_emby_settings(conn)

            if emby_settings.enabled and emby_settings.url:
                update_progress("emby", 97, "Refreshing Emby guide...")

                client = EmbyClient(
                    base_url=emby_settings.url,
                    username=emby_settings.username or "",
                    password=emby_settings.password or "",
                    api_key=emby_settings.api_key,
                )

                def on_emby_progress(pct):
                    update_progress(
                        "emby", 97, f"Refreshing Emby guide... {pct:.0f}%"
                    )

                emby_result = client.trigger_guide_refresh(
                    timeout=300,
                    on_progress=on_emby_progress,
                    cancellation_check=is_cancellation_requested,
                )
                result.emby_refresh = emby_result
                if emby_result.get("success"):
                    logger.info(
                        "[EMBY] Guide refresh completed in %.1fs",
                        emby_result.get("duration", 0),
                    )
                else:
                    logger.warning(
                        "[EMBY] Guide refresh failed: %s",
                        emby_result.get("message"),
                    )
        except Exception as e:
            logger.warning("[EMBY] Guide refresh failed (non-blocking): %s", e)
            result.emby_refresh = {"success": False, "error": str(e)}

        # Step 5c: Jellyfin Live TV guide refresh
        check_cancelled()
        try:
            from teamarr.database.settings import get_jellyfin_settings

            with db_factory() as conn:
                jellyfin_settings = get_jellyfin_settings(conn)

            if jellyfin_settings.enabled and jellyfin_settings.url:
                update_progress("jellyfin", 97, "Refreshing Jellyfin guide...")

                client = JellyfinClient(
                    base_url=jellyfin_settings.url,
                    username=jellyfin_settings.username or "",
                    password=jellyfin_settings.password or "",
                    api_key=jellyfin_settings.api_key,
                )

                def on_jellyfin_progress(pct):
                    update_progress(
                        "jellyfin", 97, f"Refreshing Jellyfin guide... {pct:.0f}%"
                    )

                jellyfin_result = client.trigger_guide_refresh(
                    timeout=300,
                    on_progress=on_jellyfin_progress,
                    cancellation_check=is_cancellation_requested,
                )
                result.jellyfin_refresh = jellyfin_result
                if jellyfin_result.get("success"):
                    logger.info(
                        "[JELLYFIN] Guide refresh completed in %.1fs",
                        jellyfin_result.get("duration", 0),
                    )
                else:
                    logger.warning(
                        "[JELLYFIN] Guide refresh failed: %s",
                        jellyfin_result.get("message"),
                    )
        except Exception as e:
            logger.warning("[JELLYFIN] Guide refresh failed (non-blocking): %s", e)
            result.jellyfin_refresh = {"success": False, "error": str(e)}

        # Step 5d: Channels DVR M3U source + XMLTV lineup refresh
        # CDVR splits channel-list and EPG into two providers — without the
        # lineup PUT the channels are fresh but the guide is stale.
        check_cancelled()
        try:
            from teamarr.database.settings import get_channelsdvr_settings

            with db_factory() as conn:
                channelsdvr_settings = get_channelsdvr_settings(conn)

            if not (channelsdvr_settings.enabled and channelsdvr_settings.url):
                pass  # integration off or unconfigured — nothing to do
            else:

                # The client derives lineup_id as "XMLTV-<source_name>" when no
                # lineup is explicitly configured, so the guide refresh fires
                # even if the user only set the M3U source.
                client = ChannelsDVRClient(
                    base_url=channelsdvr_settings.url,
                    source_name=channelsdvr_settings.source_name or "",
                    lineup_id=channelsdvr_settings.lineup_id or "",
                )

                if not (client.source_name or client.lineup_id):
                    logger.warning(
                        "[CHANNELSDVR] Enabled but no source name or XMLTV lineup "
                        "configured — nothing to refresh. Set a source name "
                        "(and optionally a lineup) in Settings."
                    )
                else:
                    # Sequence the two refreshes on real evidence: wait for the
                    # M3U channel-list refresh to actually finish before firing
                    # the guide PUT, so the guide doesn't index against a stale
                    # channel list. Both waits poll CDVR /log (see client docs).
                    if client.source_name:
                        update_progress(
                            "channelsdvr", 97, "Refreshing Channels DVR channels..."
                        )
                        m3u_result = client.trigger_m3u_refresh(
                            timeout=60, wait_for_completion=bool(client.lineup_id)
                        )
                        result.channelsdvr_refresh = m3u_result
                        if m3u_result.get("success"):
                            logger.info(
                                "[CHANNELSDVR] M3U refresh triggered in %.1fs (completion: %s)",
                                m3u_result.get("duration", 0),
                                m3u_result.get("completed", "not awaited"),
                            )
                        else:
                            logger.warning(
                                "[CHANNELSDVR] M3U refresh failed: %s",
                                m3u_result.get("message"),
                            )

                    if client.lineup_id:
                        if client.lineup_derived:
                            logger.info(
                                "[CHANNELSDVR] No XMLTV lineup configured; "
                                "derived '%s' from source '%s'",
                                client.lineup_id,
                                client.source_name,
                            )
                        update_progress(
                            "channelsdvr", 97, "Refreshing Channels DVR guide..."
                        )
                        epg_result = client.trigger_epg_refresh(timeout=60, verify=True)
                        result.channelsdvr_epg_refresh = epg_result
                        if not epg_result.get("success"):
                            logger.warning(
                                "[CHANNELSDVR] EPG refresh failed: %s",
                                epg_result.get("message"),
                            )
                        else:
                            verification = epg_result.get("verification") or {}
                            status = verification.get("status")
                            if status == "no_fetch":
                                logger.warning(
                                    "[CHANNELSDVR] EPG refresh accepted but guide "
                                    "'%s' was not re-fetched — guide may be stale",
                                    client.lineup_id,
                                )
                            else:
                                logger.info(
                                    "[CHANNELSDVR] EPG refresh for lineup '%s' in "
                                    "%.1fs (verification: %s)",
                                    client.lineup_id,
                                    epg_result.get("duration", 0),
                                    status or "not verified",
                                )
                    else:
                        logger.warning(
                            "[CHANNELSDVR] Skipping EPG/guide refresh: no XMLTV "
                            "lineup configured and none could be derived (set a "
                            "source name so the lineup can be inferred). The "
                            "guide will stay stale until refreshed manually."
                        )
        except Exception as e:
            logger.warning(
                "[CHANNELSDVR] Refresh failed (non-blocking): %s", e
            )
            result.channelsdvr_refresh = {"success": False, "error": str(e)}

        # Step 6: Process scheduled deletions (98-99%)
        check_cancelled()
        update_progress("lifecycle", 98, "Processing scheduled deletions...")
        channels_deleted_count = 0
        try:
            deletion_result = lifecycle_service.process_scheduled_deletions()
            channels_deleted_count = len(deletion_result.deleted)
            result.deletions = {
                "deleted_count": channels_deleted_count,
                "error_count": len(deletion_result.errors),
            }
            if deletion_result.deleted:
                logger.info("[GENERATION] Deleted %d expired channel(s)", channels_deleted_count)
        except Exception as e:
            logger.warning("[GENERATION] Scheduled deletions failed: %s", e)
            result.deletions = {"error": str(e)}

        # Step 7: Run reconciliation + cleanup (99-100%)
        check_cancelled()
        update_progress("reconciliation", 99, "Running reconciliation...")
        try:
            with db_factory() as conn:
                recon_settings = get_reconciliation_settings(conn)
            if recon_settings.get("reconcile_on_epg_generation", True):
                reconciler = create_reconciler(db_factory, dispatcharr_client)
                recon_result = reconciler.reconcile(auto_fix=False)
                result.reconciliation = recon_result.summary
                if recon_result.issues_found:
                    logger.info("[RECONCILE] Found %d issue(s)", len(recon_result.issues_found))
        except Exception as e:
            logger.warning("[RECONCILE] Failed: %s", e)
            result.reconciliation = {"error": str(e)}

        # Step 7b: Stale source-group detection (lylt.1) — flag enabled groups
        # whose Dispatcharr M3U source channel-group no longer exists.
        try:
            detect_stale_groups(db_factory)
        except Exception as e:
            logger.warning("[STALE_GROUPS] Detection failed: %s", e)

        # DIAG: Post-generation stream audit — compare DB vs Dispatcharr
        try:
            _run_stream_audit(db_factory, dispatcharr_client)
        except Exception as e:
            logger.warning("[STREAM_AUDIT] Post-generation audit failed: %s", e)

        # Cleanup (history, old runs, unused logos — part of step 7)
        check_cancelled()
        update_progress("cleanup", 99, "Cleaning up history...")
        cleanup_results = _run_cleanup_tasks(db_factory, dispatcharr_client, update_progress)
        result.cleanup = cleanup_results["history"]
        result.logo_cleanup = cleanup_results["logos"]

        # Update and save stats run
        _finalize_stats_run(
            stats_run, result, team_result, group_result,
            channels_deleted_count, db_factory,
        )

        result.completed_at = time.time()
        result.duration_seconds = round(result.completed_at - result.started_at, 1)
        result.success = True

        update_progress("complete", 100, "Generation complete")

        # Flush the service cache to SQLite for immediate persistence

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

        # Save cancelled run
        try:
            from teamarr.database.stats import save_run as _save_run

            stats_run.complete(status="cancelled", error="Cancelled by user")
            with db_factory() as conn:
                _save_run(conn, stats_run)
        except Exception as save_err:
            logger.warning("[GENERATION] Failed to save cancelled run stats: %s", save_err)

    except Exception as e:
        logger.exception("[GENERATION] Failed: %s", e)
        result.success = False
        result.error = str(e)
        result.completed_at = time.time()
        result.duration_seconds = round(result.completed_at - result.started_at, 1)

        # Save failed run
        try:
            from teamarr.database.stats import save_run as _save_run

            stats_run.complete(status="failed", error=str(e))
            with db_factory() as conn:
                _save_run(conn, stats_run)
        except Exception as save_err:
            logger.warning("[GENERATION] Failed to save failed run stats: %s", save_err)

    finally:
        # Always release the lock
        _generation_running = False
        _generation_lock.release()

    return result


def _refresh_m3u_accounts(db_factory: Callable[[], Any], dispatcharr_client: Any) -> dict:
    """Refresh M3U accounts for all event groups."""
    from teamarr.database.groups import get_all_groups

    result = {"refreshed": 0, "skipped": 0, "failed": 0, "account_ids": []}

    # Collect unique M3U account IDs from active groups
    with db_factory() as conn:
        groups = get_all_groups(conn, include_disabled=False)

    account_ids = set()
    for group in groups:
        if group.m3u_account_id:
            account_ids.add(group.m3u_account_id)

    if not account_ids:
        return result

    result["account_ids"] = list(account_ids)

    # Refresh all accounts in parallel

    raw_client = (
        dispatcharr_client.client
        if isinstance(dispatcharr_client, DispatcharrConnection)
        else dispatcharr_client
    )
    m3u_manager = M3UManager(raw_client)
    batch_result = m3u_manager.refresh_multiple(
        list(account_ids),
        timeout=300,
        skip_if_recent_minutes=30,
    )

    result["refreshed"] = batch_result.succeeded_count - batch_result.skipped_count
    result["skipped"] = batch_result.skipped_count
    result["failed"] = batch_result.failed_count
    result["duration"] = batch_result.duration

    if batch_result.succeeded_count > 0:
        logger.info(
            "[M3U] Refresh: %d refreshed, %d skipped (recently updated)",
            result["refreshed"],
            result["skipped"],
        )

    return result


def _validate_channel_ranges(
    db_factory: Callable[[], Any],
    external_occupied: set[int],
) -> dict:
    """Validate global channel range against external Dispatcharr channels.

    Checks for overlap between the configured channel range and external
    channels. Returns conflict info for the generation result (#146).

    Args:
        db_factory: Factory function returning database connection
        external_occupied: Channel numbers occupied by non-Teamarr channels

    Returns:
        Dict with external channel stats and range warnings
    """
    from teamarr.database.channel_numbers import get_global_channel_range

    max_external = max(external_occupied) if external_occupied else 0
    conflicts: dict = {
        "external_channels_detected": len(external_occupied),
        "max_external_channel": max_external,
        "group_warnings": [],
    }

    with db_factory() as conn:
        range_start, range_end = get_global_channel_range(conn)
        effective_end = range_end if range_end else range_start + 9999
        global_range = set(range(range_start, effective_end + 1))
        collisions = external_occupied & global_range

        if collisions:
            available = len(global_range) - len(collisions)
            warning = {
                "group_id": None,
                "group_name": "Global Range",
                "range": f"{range_start}-{effective_end}",
                "external_collisions": len(collisions),
                "available_slots": available,
            }
            conflicts["group_warnings"].append(warning)
            logger.warning(
                "[CHANNEL_NUM] Global range %d-%d has %d "
                "external channel collisions (%d slots available)",
                range_start,
                effective_end,
                len(collisions),
                available,
            )

    if not conflicts["group_warnings"]:
        logger.info(
            "[CHANNEL_NUM] No channel range conflicts "
            "with %d external channels",
            len(external_occupied),
        )

    return conflicts


def _sync_global_channels(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
    update_progress: Callable,
    external_occupied: set[int] | None = None,
) -> None:
    """Reassign channel numbers globally by sort priority.

    This is the single authoritative pass that pushes numbers to Dispatcharr.
    In sticky (gap/strict) modes it places only new channels, unless the daily
    reset window has arrived (should_run_channel_reset) — then it re-grids
    everything once.
    """
    from teamarr.database.channel_numbers import (
        reassign_all_channels,
        should_run_channel_reset,
    )

    update_progress("groups", 94, "Reassigning channels globally by sport/league priority...")
    with db_factory() as conn:
        force_reset = should_run_channel_reset(conn)
        if force_reset:
            update_progress("groups", 94, "Daily channel re-layout (low-traffic reset)...")
        global_result = reassign_all_channels(
            conn, external_occupied=external_occupied, force_reset=force_reset
        )
        if global_result["channels_moved"] == 0:
            return

        logger.info(
            "[GENERATION] Global reassignment: %d channels processed, %d moved",
            global_result["channels_processed"],
            global_result["channels_moved"],
        )

        if not dispatcharr_client:
            return

        synced = 0
        for ch in global_result.get("drift_details", []):
            disp_id = ch.get("dispatcharr_channel_id")
            new_num = ch.get("new_number")
            if disp_id and new_num:
                try:
                    dispatcharr_client.channels.update_channel(
                        disp_id, {"channel_number": new_num}
                    )
                    synced += 1
                except Exception as e:
                    logger.warning(
                        "[GENERATION] Failed to sync channel %s to Dispatcharr: %s",
                        ch.get("channel_name"),
                        e,
                    )
        if synced:
            logger.info("[GENERATION] Synced %d channel numbers to Dispatcharr", synced)


def _apply_stream_ordering(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
    update_progress: Callable,
) -> dict:
    """Apply stream ordering rules to all managed channels."""
    from teamarr.database.channels import (
        get_all_managed_channels,
        get_channel_streams,
        get_ordered_stream_ids,
        update_stream_priority,
    )
    from teamarr.database.settings import get_stream_ordering_settings

    reorder_result: dict = {
        "channels_reordered": 0,
        "streams_reordered": 0,
        "windows_synced": 0,
    }
    try:
        with db_factory() as conn:
            ordering_settings = get_stream_ordering_settings(conn)
            # No early return when rules are absent: time-windowed (EPG-matched)
            # streams still need their membership synced each run so they attach
            # when their window opens and detach when it closes (bead teamarrv2-uye).
            ordering_service = (
                StreamOrderingService(rules=ordering_settings.rules, conn=conn)
                if ordering_settings.rules
                else None
            )
            if ordering_service:
                logger.info(
                    "[ORDERING] Applying %d ordering rule(s)", len(ordering_settings.rules)
                )
            else:
                logger.debug(
                    "[ORDERING] No ordering rules configured; running window sync only"
                )

            # Setup Dispatcharr channel manager once if available
            channel_mgr = None
            if dispatcharr_client:

                raw_client = (
                    dispatcharr_client.client
                    if isinstance(dispatcharr_client, DispatcharrConnection)
                    else dispatcharr_client
                )
                channel_mgr = ChannelManager(raw_client)

            all_channels = get_all_managed_channels(conn, include_deleted=False)
            total_channels = len(all_channels)

            for idx, channel in enumerate(all_channels):
                streams = get_channel_streams(conn, channel.id)
                if not streams:
                    continue

                reordered_count = 0
                if ordering_service:
                    for stream in streams:
                        new_priority = ordering_service.compute_priority(stream)
                        if stream.priority != new_priority:
                            update_stream_priority(conn, stream.id, new_priority)
                            reordered_count += 1

                if reordered_count > 0:
                    reorder_result["channels_reordered"] += 1
                    reorder_result["streams_reordered"] += reordered_count

                # Push the window-gated active set to Dispatcharr when priorities
                # changed OR the channel has any time-windowed stream (whose
                # membership flips as its attach/detach window opens and closes).
                # An empty set IS pushed — a channel whose sole source is currently
                # out-of-window must be cleared (it re-attaches on a later run).
                has_windowed = any(s.attach_at for s in streams)
                if (reordered_count > 0 or has_windowed) and (
                    channel_mgr and channel.dispatcharr_channel_id
                ):
                    ordered_ids = get_ordered_stream_ids(conn, channel.id)
                    if has_windowed:
                        reorder_result["windows_synced"] += 1
                    logger.info(
                        "[STREAM_AUDIT] sync: ch='%s' (d_id=%s) setting streams=%s "
                        "count=%d (reordered=%d windowed=%s)",
                        channel.channel_name,
                        channel.dispatcharr_channel_id,
                        ordered_ids,
                        len(ordered_ids),
                        reordered_count,
                        has_windowed,
                    )
                    sync_result = channel_mgr.update_channel(
                        channel.dispatcharr_channel_id, {"streams": ordered_ids}
                    )
                    if not sync_result.success:
                        logger.warning(
                            "[ORDERING] Failed to sync channel %s to Dispatcharr: %s",
                            channel.channel_name,
                            sync_result.error,
                        )

                if (idx + 1) % 10 == 0 or idx == total_channels - 1:
                    pct = 93 + int(((idx + 1) / total_channels) * 2)
                    update_progress(
                        "ordering",
                        pct,
                        f"Ordering streams ({idx + 1}/{total_channels})",
                        idx + 1,
                        total_channels,
                        channel.channel_name,
                    )

            if reorder_result["channels_reordered"] > 0 or reorder_result["windows_synced"] > 0:
                logger.info(
                    "[ORDERING] Reordered %d streams across %d channels; "
                    "window-synced %d channel(s)",
                    reorder_result["streams_reordered"],
                    reorder_result["channels_reordered"],
                    reorder_result["windows_synced"],
                )
    except Exception as e:
        logger.warning("[ORDERING] Stream ordering failed: %s", e)
        reorder_result["error"] = str(e)

    return reorder_result


def _run_stream_audit(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
) -> None:
    """Post-generation audit: compare DB stream counts vs Dispatcharr.

    Logs any channels where the DB and Dispatcharr disagree on stream
    assignments. This is diagnostic-only — no changes are made.
    """
    from teamarr.database.channels import get_all_managed_channels, get_ordered_stream_ids

    if not dispatcharr_client:
        return

    channel_attr = getattr(dispatcharr_client, "channels", None)
    raw_client = channel_attr._client if channel_attr else None
    if not raw_client:
        return

    channel_mgr = ChannelManager(raw_client)
    mismatches = []

    with db_factory() as conn:
        channels = get_all_managed_channels(conn, include_deleted=False)

        for channel in channels:
            if not channel.dispatcharr_channel_id:
                continue

            # Window-gated active set (same set we actually push to Dispatcharr).
            # Using the raw stream list here would false-flag time-shared EPG
            # streams that are correctly out of their attach/detach window (183.5)
            # as mismatches. Mirrors reconciliation's expected-set logic.
            db_stream_ids = sorted(get_ordered_stream_ids(conn, channel.id))

            d_channel = channel_mgr.get_channel(channel.dispatcharr_channel_id)
            if not d_channel:
                logger.warning(
                    "[STREAM_AUDIT] MISSING: ch='%s' (d_id=%s) exists in DB "
                    "but not in Dispatcharr (db_streams=%s)",
                    channel.channel_name,
                    channel.dispatcharr_channel_id,
                    db_stream_ids,
                )
                continue

            d_stream_ids = sorted(d_channel.streams or ())

            if db_stream_ids != d_stream_ids:
                mismatches.append(channel.channel_name)
                logger.warning(
                    "[STREAM_AUDIT] MISMATCH: ch='%s' (d_id=%s) "
                    "db_streams=%s (%d) vs dispatcharr_streams=%s (%d)",
                    channel.channel_name,
                    channel.dispatcharr_channel_id,
                    db_stream_ids,
                    len(db_stream_ids),
                    d_stream_ids,
                    len(d_stream_ids),
                )

    if mismatches:
        logger.warning(
            "[STREAM_AUDIT] %d channel(s) have stream mismatches: %s",
            len(mismatches),
            mismatches[:20],  # Cap at 20 to avoid log spam
        )
    else:
        logger.info("[STREAM_AUDIT] All channels match between DB and Dispatcharr")


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
    stats_run.channels_deleted = channels_deleted_count + group_result.total_channels_deleted
    stats_run.xmltv_size_bytes = result.file_size
    stats_run.streams_fetched = group_result.total_streams_fetched
    stats_run.streams_matched = group_result.total_streams_matched
    stats_run.streams_unmatched = group_result.total_streams_unmatched
    stats_run.extra_metrics["teams_processed"] = result.teams_processed
    stats_run.extra_metrics["groups_processed"] = result.groups_processed
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

    with db_factory() as conn:
        active_channels = get_all_managed_channels(conn, include_deleted=False)
        stats_run.channels_active = len(active_channels)
        logger.info("[GENERATION] %d active managed channels", len(active_channels))

    stats_run.complete(status="completed")

    with db_factory() as conn:
        save_run(conn, stats_run)

