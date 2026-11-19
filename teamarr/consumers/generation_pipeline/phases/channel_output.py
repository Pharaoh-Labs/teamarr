"""Channel-number assignment and XMLTV publication phases."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

from teamarr.utilities.xmltv import merge_xmltv_content

if TYPE_CHECKING:  # pragma: no cover - typing only
    from teamarr.consumers.generation_pipeline.models import GenerationContext

logger = logging.getLogger(__name__)


def stage_channel_reassign(
    context: GenerationContext,
    sync_global_channels: Callable[[Callable[[], Any], Any, Callable, set[int] | None], bool]
    | None = None,
) -> None:
    """Apply the global numbering pass after group processing."""
    context.relayout = (sync_global_channels or reassign_global_channels)(
        context.db_factory,
        context.dispatcharr_client,
        context.report,
        context.external_occupied,
    )


def stage_xmltv_save(
    context: GenerationContext,
    get_team_xmltv: Callable[[Any], list[str]] | None = None,
    get_group_xmltv: Callable[[Any], list[str]] | None = None,
    merge_xmltv: Callable[..., str] = merge_xmltv_content,
) -> None:
    """Merge team then group XMLTV and publish it to the configured path."""
    if get_team_xmltv is None:
        from teamarr.consumers.team_processor import get_all_team_xmltv

        get_team_xmltv = get_all_team_xmltv
    if get_group_xmltv is None:
        from teamarr.database.groups import get_all_group_xmltv

        get_group_xmltv = get_all_group_xmltv

    context.report("saving", 95, "Saving XMLTV...")
    with context.db_factory() as conn:
        xmltv_contents = get_team_xmltv(conn) + get_group_xmltv(conn)
    output_path = context.settings.epg.epg_output_path
    if not (xmltv_contents and output_path):
        return

    merged = merge_xmltv(
        xmltv_contents,
        generator_name=context.settings.display.xmltv_generator_name,
        generator_url=context.settings.display.xmltv_generator_url,
    )
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(merged, encoding="utf-8")
    context.result.file_written = True
    context.result.file_path = str(output_file.absolute())
    context.result.file_size = len(merged)
    logger.info("[GENERATION] EPG written to %s (%s bytes)", output_path, f"{len(merged):,}")


def reassign_global_channels(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
    update_progress: Callable,
    external_occupied: set[int] | None = None,
) -> bool:
    """Reassign channel numbers globally by sort priority."""
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
            return force_reset

        logger.info(
            "[GENERATION] Global reassignment: %d channels processed, %d moved",
            global_result["channels_processed"],
            global_result["channels_moved"],
        )

    if not dispatcharr_client:
        return force_reset

    moves = [
        move
        for move in global_result.get("drift_details", [])
        if move.get("dispatcharr_channel_id") and move.get("new_number")
    ]

    def push(move: dict) -> bool:
        try:
            outcome = dispatcharr_client.channels.update_channel(
                move["dispatcharr_channel_id"], {"channel_number": move["new_number"]}
            )
            if outcome.success:
                return True
            logger.warning(
                "[GENERATION] Failed to sync channel %s to Dispatcharr: %s",
                move.get("channel_name"),
                outcome.error,
            )
        except Exception as exc:  # noqa: BLE001 - per-channel isolation
            logger.warning(
                "[GENERATION] Failed to sync channel %s to Dispatcharr: %s",
                move.get("channel_name"),
                exc,
            )
        return False

    old_numbers = {move.get("old_number") for move in moves}
    new_numbers = {move["new_number"] for move in moves}
    # Moves that need an occupied slot retain the allocator's serial order.
    independent = None not in old_numbers and not old_numbers.intersection(new_numbers)
    if len(moves) > 1 and independent and len(new_numbers) == len(moves):
        with ThreadPoolExecutor(max_workers=8, thread_name_prefix="channel-number") as executor:
            synced = sum(executor.map(push, moves))
    else:
        synced = sum(map(push, moves))
    if synced:
        logger.info("[GENERATION] Synced %d channel numbers to Dispatcharr", synced)
    return force_reset


__all__ = ["reassign_global_channels", "stage_channel_reassign", "stage_xmltv_save"]
