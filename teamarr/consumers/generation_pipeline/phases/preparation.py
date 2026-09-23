"""Early generation preparation phases."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from teamarr.dispatcharr import M3UManager
from teamarr.dispatcharr.factory import DispatcharrConnection
from teamarr.services import TeamChannelManager

if TYPE_CHECKING:  # pragma: no cover - typing only
    from teamarr.consumers.generation_pipeline.models import GenerationContext

logger = logging.getLogger(__name__)


def stage_m3u_refresh(
    context: GenerationContext,
    refresh_m3u_accounts: Callable[[Callable[[], Any], Any], dict] | None = None,
) -> None:
    """Refresh M3U accounts before team and group processing."""
    context.report("init", 3, "Refreshing M3U accounts...")
    if context.dispatcharr_client:
        context.result.m3u_refresh = (refresh_m3u_accounts or refresh_m3u_accounts_for_groups)(
            context.db_factory, context.dispatcharr_client
        )


def stage_prepare_team_channels(context: GenerationContext) -> None:
    """Build the managed team-channel coordinator after team processing."""
    team_channels = (
        context.dispatcharr_client
        if isinstance(context.dispatcharr_client, DispatcharrConnection)
        else None
    )
    context.team_channel_manager = TeamChannelManager(
        context.db_factory,
        team_channels.channels if team_channels else None,
        team_channels.epg if team_channels else None,
        team_channels.logos if team_channels else None,
    )
    context.report(
        "groups",
        50,
        f"Teams complete ({context.result.teams_processed} processed), loading event groups...",
        0,
        1,
        "Loading event groups...",
    )


def refresh_m3u_accounts_for_groups(
    db_factory: Callable[[], Any], dispatcharr_client: Any
) -> dict:
    """Refresh M3U accounts for all enabled event groups."""
    from teamarr.database.groups import get_all_groups

    result = {"refreshed": 0, "skipped": 0, "failed": 0, "account_ids": []}
    with db_factory() as conn:
        groups = get_all_groups(conn, include_disabled=False)

    account_ids = {group.m3u_account_id for group in groups if group.m3u_account_id}
    if not account_ids:
        return result

    result["account_ids"] = list(account_ids)
    raw_client = (
        dispatcharr_client.client
        if isinstance(dispatcharr_client, DispatcharrConnection)
        else dispatcharr_client
    )
    batch_result = M3UManager(raw_client).refresh_multiple(
        list(account_ids), timeout=300, skip_if_recent_minutes=30
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


__all__ = [
    "refresh_m3u_accounts_for_groups",
    "stage_m3u_refresh",
    "stage_prepare_team_channels",
]
