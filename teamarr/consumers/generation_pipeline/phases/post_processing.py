"""Lifecycle and reconciliation phases for the fixed generation pipeline."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from teamarr.dispatcharr import EPGManager
from teamarr.dispatcharr.factory import DispatcharrConnection

if TYPE_CHECKING:  # pragma: no cover - typing only
    from teamarr.consumers.generation_pipeline.models import GenerationContext

# Preserve the established façade logger name for log-based diagnostics.
logger = logging.getLogger("teamarr.consumers.generation")


def stage_lifecycle_prepare(
    context: GenerationContext,
    lifecycle_factory: Callable[..., Any],
) -> None:
    """Construct lifecycle services and synchronize their prerequisite state."""
    lifecycle_service = lifecycle_factory(
        context.db_factory,
        context.sports_service,
        dispatcharr_client=context.dispatcharr_client,
    )
    context.lifecycle_service = lifecycle_service
    lifecycle_service.compute_external_occupied()
    lifecycle_service.sync_stream_profiles()


def stage_dispatcharr_epg(
    context: GenerationContext,
    cancellation_requested: Callable[[], bool],
) -> None:
    """Refresh Dispatcharr EPG and associate it with managed channels."""
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
        cancellation_check=cancellation_requested,
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


def stage_deletions(context: GenerationContext) -> None:
    """Process scheduled channel deletions without failing the generation run."""
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
    except Exception as exc:  # noqa: BLE001 - existing nonfatal boundary
        logger.warning("[GENERATION] Scheduled deletions failed: %s", exc)
        context.result.deletions = {"error": str(exc)}


def stage_reconciliation(
    context: GenerationContext,
    reconciler_factory: Callable[..., Any],
    reconciliation_settings: Callable[[Any], dict],
) -> None:
    """Run optional reconciliation while preserving its nonfatal failure policy."""
    context.report("reconciliation", 99, "Running reconciliation...")
    try:
        with context.db_factory() as conn:
            settings = reconciliation_settings(conn)
        if settings.get("reconcile_on_epg_generation", True):
            reconciliation = reconciler_factory(
                context.db_factory, context.dispatcharr_client
            ).reconcile(auto_fix=False)
            context.result.reconciliation = reconciliation.summary
            if reconciliation.issues_found:
                logger.info("[RECONCILE] Found %d issue(s)", len(reconciliation.issues_found))
    except Exception as exc:  # noqa: BLE001 - existing nonfatal boundary
        logger.warning("[RECONCILE] Failed: %s", exc)
        context.result.reconciliation = {"error": str(exc)}


def stage_stream_audit(
    context: GenerationContext,
    stale_group_detector: Callable[[Callable[[], Any]], Any],
    stream_audit: Callable[[Callable[[], Any], Any], None],
) -> None:
    """Run stale-group and stream audit diagnostics without mutating channels."""
    try:
        stale_group_detector(context.db_factory)
    except Exception as exc:  # noqa: BLE001 - existing nonfatal boundary
        logger.warning("[STALE_GROUPS] Detection failed: %s", exc)
    try:
        stream_audit(context.db_factory, context.dispatcharr_client)
    except Exception as exc:  # noqa: BLE001 - existing nonfatal boundary
        logger.warning("[STREAM_AUDIT] Post-generation audit failed: %s", exc)


__all__ = [
    "stage_deletions",
    "stage_dispatcharr_epg",
    "stage_lifecycle_prepare",
    "stage_reconciliation",
    "stage_stream_audit",
]
