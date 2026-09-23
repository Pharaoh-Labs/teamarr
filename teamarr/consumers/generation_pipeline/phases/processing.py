"""Team and event-group processing phases."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from teamarr.dispatcharr.factory import DispatcharrConnection

if TYPE_CHECKING:  # pragma: no cover - typing only
    from teamarr.consumers.generation_pipeline.models import GenerationContext

logger = logging.getLogger(__name__)


def stage_teams(context: GenerationContext, team_processor: Callable[..., Any]) -> None:
    """Process all teams with the run-scoped sports-data service."""
    context.report("teams", 5, "Processing teams...")
    started_at = time.time()

    def progress(current: int, total: int, name: str) -> None:
        percent = 5 + int((current / total) * 45) if total else 5
        elapsed = time.time() - started_at
        remaining = total - current
        message = (
            f"{name} ({current}/{total}) - {remaining} remaining [{elapsed:.1f}s]"
            if remaining > 0
            else f"{name} ({current}/{total}) [{elapsed:.1f}s]"
        )
        context.report("teams", percent, message, current, total, name)

    context.team_result = team_processor(
        db_factory=context.db_factory,
        progress_callback=progress,
        service=context.sports_service,
    )
    assert context.team_result is not None
    context.result.teams_processed = context.team_result.teams_processed
    context.result.teams_programmes = context.team_result.total_programmes


def stage_groups(
    context: GenerationContext,
    group_processor: Callable[..., Any],
    external_occupied_provider: Callable[[Callable[[], Any], Any], set[int]],
    validate_channel_ranges: Callable[[Callable[[], Any], set[int]], dict],
) -> None:
    """Process event groups and collect their managed team-channel streams."""
    started_at = time.time()

    def progress(current: int, total: int, name: str) -> None:
        percent = 50 + int((current / total) * 45) if total else 50
        elapsed = time.time() - started_at
        if "✓" in name or "✗" in name:
            context.report("groups", percent, name, current, total, name)
            return
        remaining = total - current
        message = (
            f"Finished {name} ({current}/{total}) - {remaining} remaining [{elapsed:.1f}s]"
            if remaining > 0
            else f"Finished {name} ({current}/{total}) [{elapsed:.1f}s]"
        )
        context.report("groups", percent, message, current, total, name)

    channel_manager = (
        context.dispatcharr_client.channels
        if isinstance(context.dispatcharr_client, DispatcharrConnection)
        else None
    )
    context.external_occupied = external_occupied_provider(context.db_factory, channel_manager)
    if context.external_occupied:
        context.result.channel_conflicts = validate_channel_ranges(
            context.db_factory, context.external_occupied
        )

    def collect_matches(group_id: int, matches: list[dict]) -> None:
        context.team_completed_groups.add(group_id)
        context.team_matched_streams.extend(
            {**match, "source_group_id": group_id} for match in matches
        )

    context.group_result = group_processor(
        db_factory=context.db_factory,
        dispatcharr_client=context.dispatcharr_client,
        progress_callback=progress,
        generation=context.current_generation,
        service=context.sports_service,
        aggregate_xmltv=False,
        run_id=context.stats_run.id,
        matched_stream_callback=collect_matches,
    )
    assert context.group_result is not None
    context.result.groups_processed = context.group_result.groups_processed
    context.result.groups_programmes = context.group_result.total_programmes
    context.result.programmes_total = (
        context.result.teams_programmes + context.result.groups_programmes
    )


def validate_channel_ranges(db_factory: Callable[[], Any], external_occupied: set[int]) -> dict:
    """Validate the global channel range against external Dispatcharr channels."""
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
            conflicts["group_warnings"].append(
                {
                    "group_id": None,
                    "group_name": "Global Range",
                    "range": f"{range_start}-{effective_end}",
                    "external_collisions": len(collisions),
                    "available_slots": available,
                }
            )
            logger.warning(
                "[CHANNEL_NUM] Global range %d-%d has %d external channel collisions "
                "(%d slots available)",
                range_start,
                effective_end,
                len(collisions),
                available,
            )

    if not conflicts["group_warnings"]:
        logger.info(
            "[CHANNEL_NUM] No channel range conflicts with %d external channels",
            len(external_occupied),
        )
    return conflicts


__all__ = ["stage_groups", "stage_teams", "validate_channel_ranges"]
