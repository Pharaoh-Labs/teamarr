"""Channel management endpoints.

Provides REST API for:
- Listing managed channels
- Manual channel operations (delete, sync)
- Reconciliation (detect and fix issues)
- Lifecycle sync (create/delete based on timing)
"""

import logging
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from teamarr.database import get_db

logger = logging.getLogger(__name__)


def _safe_isoformat(value: Any) -> str | None:
    """Safely convert a date/datetime value to ISO format string.

    Handles cases where the value might already be a string from the database.
    """
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


router = APIRouter()


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class ManagedChannelModel(BaseModel):
    """Managed channel response model."""

    id: int
    event_epg_group_id: int | None = None  # Source group (provenance)
    event_id: str
    event_provider: str
    tvg_id: str
    channel_name: str
    channel_number: str | None = None
    logo_url: str | None = None

    dispatcharr_channel_id: int | None = None
    dispatcharr_uuid: str | None = None

    home_team: str | None = None
    away_team: str | None = None
    event_date: str | None = None
    event_name: str | None = None
    league: str | None = None
    sport: str | None = None

    scheduled_delete_at: str | None = None
    sync_status: str = "pending"

    created_at: str | None = None
    updated_at: str | None = None
    deleted_at: str | None = None


class ManagedChannelListResponse(BaseModel):
    """List of managed channels."""

    channels: list[ManagedChannelModel]
    total: int


class ReconciliationRequest(BaseModel):
    """Request for reconciliation."""

    auto_fix: bool = Field(default=False, description="Automatically fix issues")


class ReconciliationIssueModel(BaseModel):
    """Single reconciliation issue."""

    issue_type: str
    severity: str
    managed_channel_id: int | None = None
    dispatcharr_channel_id: int | None = None
    channel_name: str | None = None
    event_id: str | None = None
    details: dict = {}
    suggested_action: str | None = None
    auto_fixable: bool = False


class ReconciliationSummary(BaseModel):
    """Reconciliation summary."""

    orphan_teamarr: int = 0
    orphan_dispatcharr: int = 0
    duplicate: int = 0
    drift: int = 0
    total: int = 0
    fixed: int = 0
    skipped: int = 0
    errors: int = 0


class ReconciliationResponse(BaseModel):
    """Reconciliation response."""

    started_at: str | None = None
    completed_at: str | None = None
    summary: ReconciliationSummary
    issues_found: list[ReconciliationIssueModel] = []
    issues_fixed: list[dict] = []
    issues_skipped: list[dict] = []
    errors: list[str] = []


class SyncResponse(BaseModel):
    """Channel sync response."""

    created_count: int = 0
    existing_count: int = 0
    skipped_count: int = 0
    deleted_count: int = 0
    error_count: int = 0
    created: list[dict] = []
    errors: list[dict] = []


class DeleteResponse(BaseModel):
    """Channel delete response."""

    success: bool
    message: str


class StreamRuleMatch(BaseModel):
    """One ordering rule that matched a stream (priority explainer)."""

    type: str
    value: str
    priority: int
    is_winner: bool


class StreamNameMatch(BaseModel):
    """A name token that produced a match (alias text or team-name form → team)."""

    text: str
    team: str


class ChannelStreamEntry(BaseModel):
    """A single stream attached to a managed channel, with cached stats."""

    dispatcharr_stream_id: int
    stream_name: str | None = None
    source_group: str | None = None
    m3u_account_name: str | None = None
    match_method: str | None = None
    match_type: str | None = None
    exception_keyword: str | None = None
    priority: int = 0
    stream_stats: dict | None = None
    stream_stats_updated_at: str | None = None
    matched_rules: list[StreamRuleMatch] = []
    # Cache-derived match detail (absent for EPG / dedicated matches)
    matched_event: str | None = None
    matched_league: str | None = None
    cache_match_method: str | None = None
    cache_created_at: str | None = None
    match_aliases: list[StreamNameMatch] = []
    match_patterns: list[StreamNameMatch] = []
    user_corrected: bool = False
    corrected_at: str | None = None


class ChannelStreamsResponse(BaseModel):
    """Streams attached to a managed channel."""

    streams: list[ChannelStreamEntry]
    stats_refreshed: bool = False


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("/managed", response_model=ManagedChannelListResponse)
def list_managed_channels(
    group_id: int | None = Query(None, description="Filter by source group (provenance)"),
    sport: str | None = Query(None, description="Filter by sport"),
    league: str | None = Query(None, description="Filter by league"),
    include_deleted: bool = Query(False, description="Include deleted channels"),
):
    """List all managed channels.

    Returns channels tracked by Teamarr for lifecycle management.
    Primary filters: sport, league. Secondary: group_id (source provenance).
    """
    from teamarr.database.channels import (
        get_all_managed_channels,
        get_managed_channels_for_group,
    )

    with get_db() as conn:
        if group_id:
            channels = get_managed_channels_for_group(
                conn, group_id, include_deleted=include_deleted
            )
        else:
            channels = get_all_managed_channels(
                conn, include_deleted=include_deleted,
                sport=sport, league=league,
            )

    return ManagedChannelListResponse(
        channels=[
            ManagedChannelModel(
                id=c.id,
                event_epg_group_id=c.event_epg_group_id,
                event_id=c.event_id,
                event_provider=c.event_provider,
                tvg_id=c.tvg_id,
                channel_name=c.channel_name,
                channel_number=str(c.channel_number) if c.channel_number is not None else None,
                logo_url=c.logo_url,
                dispatcharr_channel_id=c.dispatcharr_channel_id,
                dispatcharr_uuid=c.dispatcharr_uuid,
                home_team=c.home_team,
                away_team=c.away_team,
                event_date=_safe_isoformat(c.event_date),
                event_name=c.event_name,
                league=c.league,
                sport=c.sport,
                scheduled_delete_at=_safe_isoformat(c.scheduled_delete_at),
                sync_status=c.sync_status,
                created_at=_safe_isoformat(c.created_at),
                updated_at=_safe_isoformat(c.updated_at),
                deleted_at=_safe_isoformat(c.deleted_at),
            )
            for c in channels
        ],
        total=len(channels),
    )


@router.get("/managed/{channel_id}", response_model=ManagedChannelModel)
def get_managed_channel(channel_id: int):
    """Get a single managed channel by ID."""
    from teamarr.database.channels import get_managed_channel

    with get_db() as conn:
        channel = get_managed_channel(conn, channel_id)

    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel {channel_id} not found",
        )

    return ManagedChannelModel(
        id=channel.id,
        event_epg_group_id=channel.event_epg_group_id,
        event_id=channel.event_id,
        event_provider=channel.event_provider,
        tvg_id=channel.tvg_id,
        channel_name=channel.channel_name,
        channel_number=str(channel.channel_number) if channel.channel_number is not None else None,
        logo_url=channel.logo_url,
        dispatcharr_channel_id=channel.dispatcharr_channel_id,
        dispatcharr_uuid=channel.dispatcharr_uuid,
        home_team=channel.home_team,
        away_team=channel.away_team,
        event_date=_safe_isoformat(channel.event_date),
        event_name=channel.event_name,
        league=channel.league,
        sport=channel.sport,
        scheduled_delete_at=_safe_isoformat(channel.scheduled_delete_at),
        sync_status=channel.sync_status,
        created_at=_safe_isoformat(channel.created_at),
        updated_at=_safe_isoformat(channel.updated_at),
    )


@router.get("/managed/{channel_id}/streams", response_model=ChannelStreamsResponse)
def get_managed_channel_streams(channel_id: int):
    """Get active streams for a managed channel with cached stats.

    Triggers a stats refresh when any stream has null stats or stats older than 1 hour.
    Source group names are resolved from event_epg_groups via a join.
    """
    from teamarr.database.channels import get_managed_channel
    from teamarr.database.channels.streams import (
        get_channel_streams,
        get_stream_match_details,
        refresh_stream_stats,
    )
    from teamarr.services.stream_ordering import get_stream_ordering_service

    with get_db() as conn:
        channel = get_managed_channel(conn, channel_id)
        if not channel:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Channel {channel_id} not found",
            )

        streams = get_channel_streams(conn, channel_id)

        # Resolve source group names in one query
        group_ids = {s.source_group_id for s in streams if s.source_group_id is not None}
        group_names: dict[int, str] = {}
        if group_ids:
            placeholders = ",".join("?" * len(group_ids))
            rows = conn.execute(
                f"SELECT id, name FROM event_epg_groups WHERE id IN ({placeholders})",
                list(group_ids),
            ).fetchall()
            group_names = {row[0]: row[1] for row in rows}

        # Refresh stats when any stream has null stats or stats older than 1 hour
        needs_refresh = any(
            s.stream_stats is None or (
                s.stream_stats_updated_at is not None and (
                    datetime.now(timezone.utc) - datetime.fromisoformat(  # noqa: UP017
                        str(s.stream_stats_updated_at).replace("Z", "+00:00")
                    )
                ).total_seconds() > 3600
            )
            for s in streams
        )

        stats_refreshed = False
        if needs_refresh and streams:
            updated = refresh_stream_stats(conn, channel_id)
            if updated:
                streams = get_channel_streams(conn, channel_id)
                stats_refreshed = True

        # Explain each stream's priority: which ordering rules currently match it.
        ordering_service = get_stream_ordering_service(conn)
        matched_by_stream: dict[int, list[StreamRuleMatch]] = {
            s.dispatcharr_stream_id: [
                StreamRuleMatch(
                    type=e.type, value=e.value, priority=e.priority, is_winner=e.is_winner
                )
                for e in ordering_service.evaluate_rules(
                    s, group_names.get(s.source_group_id) if s.source_group_id else None
                )
            ]
            for s in streams
        }

        # Explain how each stream matched its event (cache-derived; absent for
        # EPG / dedicated matches that bypass the fingerprint cache).
        match_pairs = [
            (s.source_group_id, s.dispatcharr_stream_id)
            for s in streams
            if s.source_group_id is not None
        ]
        match_details = get_stream_match_details(conn, match_pairs)

    # The channel represents one event; that's the authoritative matched event for
    # every stream on it. (The fingerprint cache can't be trusted here: EPG streams
    # are time-shared across many event channels, so a stream's cache row points at
    # whatever it last matched, not this channel's event.)
    if channel.home_team or channel.away_team:
        channel_event = f"{channel.away_team or ''} @ {channel.home_team or ''}".strip()
    else:
        channel_event = channel.event_name

    return ChannelStreamsResponse(
        streams=[
            ChannelStreamEntry(
                dispatcharr_stream_id=s.dispatcharr_stream_id,
                stream_name=s.stream_name,
                source_group=group_names.get(s.source_group_id) if s.source_group_id else None,
                m3u_account_name=s.m3u_account_name,
                match_method=s.match_method,
                match_type=s.match_type,
                exception_keyword=s.exception_keyword,
                priority=s.priority,
                stream_stats=s.stream_stats,
                stream_stats_updated_at=_safe_isoformat(s.stream_stats_updated_at),
                matched_rules=matched_by_stream.get(s.dispatcharr_stream_id, []),
                matched_event=channel_event,
                matched_league=channel.league,
                cache_match_method=(d := match_details.get(
                    (s.source_group_id, s.dispatcharr_stream_id), {}
                )).get("match_method"),
                cache_created_at=(
                    _safe_isoformat(d.get("created_at"))
                    if d.get("match_method") == "cache"
                    else None
                ),
                match_aliases=[
                    StreamNameMatch(text=a["alias"], team=a["team"])
                    for a in d.get("aliases", [])
                ],
                match_patterns=[
                    StreamNameMatch(text=p["token"], team=p["team"])
                    for p in d.get("patterns", [])
                ],
                user_corrected=d.get("user_corrected", False),
                corrected_at=_safe_isoformat(d.get("corrected_at")),
            )
            for s in streams
        ],
        stats_refreshed=stats_refreshed,
    )


@router.delete("/managed/{channel_id}", response_model=DeleteResponse)
def delete_managed_channel(channel_id: int):
    """Delete a managed channel.

    Removes the channel from Dispatcharr (if configured) and marks as deleted in DB.
    """
    from teamarr.database.channels import get_managed_channel
    from teamarr.dispatcharr import get_dispatcharr_client
    from teamarr.services import create_channel_service, create_default_service

    with get_db() as conn:
        channel = get_managed_channel(conn, channel_id)
        if not channel:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Channel {channel_id} not found",
            )

    # Get Dispatcharr client (may be None if not configured)
    try:
        client = get_dispatcharr_client(get_db)
    except Exception:
        client = None

    # Get sports service for template resolution
    sports_service = create_default_service()
    channel_service = create_channel_service(get_db, sports_service, client)

    with get_db() as conn:
        success = channel_service.delete_channel(conn, channel_id, reason="manual")

    if success:
        return DeleteResponse(
            success=True,
            message=f"Channel '{channel.channel_name}' deleted",
        )
    else:
        return DeleteResponse(
            success=False,
            message="Failed to delete channel",
        )


@router.post("/sync", response_model=SyncResponse)
def sync_lifecycle():
    """Trigger lifecycle sync.

    Creates channels that are due and deletes expired channels.
    Requires Dispatcharr to be configured.
    """
    from teamarr.database.settings import get_dispatcharr_settings
    from teamarr.dispatcharr import get_dispatcharr_client
    from teamarr.services import create_channel_service, create_default_service

    with get_db() as conn:
        settings = get_dispatcharr_settings(conn)

    if not settings.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dispatcharr not configured",
        )

    # Get Dispatcharr client
    try:
        client = get_dispatcharr_client(get_db)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect to Dispatcharr: {e}",
        ) from e

    if not client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dispatcharr connection not available",
        )

    # Get sports service for template resolution
    sports_service = create_default_service()
    channel_service = create_channel_service(get_db, sports_service, client)

    # Process scheduled deletions
    result = channel_service.process_scheduled_deletions()

    return SyncResponse(
        deleted_count=len(result.deleted),
        error_count=len(result.errors),
        errors=result.errors,
    )


@router.get("/reconciliation/status", response_model=ReconciliationResponse)
def get_reconciliation_status():
    """Get reconciliation status (detect only).

    Checks all channels for issues without making any changes.
    """
    from teamarr.database.settings import get_dispatcharr_settings
    from teamarr.dispatcharr import get_dispatcharr_client
    from teamarr.services import create_channel_service, create_default_service

    with get_db() as conn:
        settings = get_dispatcharr_settings(conn)

    if not settings.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dispatcharr not configured",
        )

    # Get Dispatcharr client
    try:
        client = get_dispatcharr_client(get_db)
    except Exception:
        client = None

    sports_service = create_default_service()
    channel_service = create_channel_service(get_db, sports_service, client)

    # Run detect-only
    result = channel_service.reconcile(auto_fix=False)

    return ReconciliationResponse(
        started_at=result.started_at.isoformat() if result.started_at else None,
        completed_at=result.completed_at.isoformat() if result.completed_at else None,
        summary=ReconciliationSummary(
            orphan_teamarr=result.summary.orphan_teamarr,
            orphan_dispatcharr=result.summary.orphan_dispatcharr,
            duplicate=result.summary.duplicates,
            drift=result.summary.drift,
        ),
        issues_found=[
            ReconciliationIssueModel(
                issue_type=i.issue_type,
                severity=i.severity,
                managed_channel_id=i.managed_channel_id,
                dispatcharr_channel_id=i.dispatcharr_channel_id,
                channel_name=i.channel_name,
                event_id=i.event_id,
                details=i.details,
                suggested_action=i.suggested_action,
                auto_fixable=i.auto_fixable,
            )
            for i in result.issues_found
        ],
        issues_fixed=[],
        issues_skipped=[],
        errors=result.errors,
    )


@router.post("/reconciliation/fix", response_model=ReconciliationResponse)
def fix_reconciliation(request: ReconciliationRequest):
    """Run reconciliation with optional auto-fix.

    Detects issues and optionally fixes them based on settings.
    """
    from teamarr.database.settings import get_dispatcharr_settings
    from teamarr.dispatcharr import get_dispatcharr_client
    from teamarr.services import create_channel_service, create_default_service

    with get_db() as conn:
        settings = get_dispatcharr_settings(conn)

    if not settings.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dispatcharr not configured",
        )

    # Get Dispatcharr client
    try:
        client = get_dispatcharr_client(get_db)
    except Exception as e:
        if request.auto_fix:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Cannot auto-fix without Dispatcharr connection: {e}",
            ) from e
        client = None

    sports_service = create_default_service()
    channel_service = create_channel_service(get_db, sports_service, client)

    # Run reconciliation
    result = channel_service.reconcile(auto_fix=request.auto_fix)

    return ReconciliationResponse(
        started_at=result.started_at.isoformat() if result.started_at else None,
        completed_at=result.completed_at.isoformat() if result.completed_at else None,
        summary=ReconciliationSummary(
            orphan_teamarr=result.summary.orphan_teamarr,
            orphan_dispatcharr=result.summary.orphan_dispatcharr,
            duplicate=result.summary.duplicates,
            drift=result.summary.drift,
        ),
        issues_found=[
            ReconciliationIssueModel(
                issue_type=i.issue_type,
                severity=i.severity,
                managed_channel_id=i.managed_channel_id,
                dispatcharr_channel_id=i.dispatcharr_channel_id,
                channel_name=i.channel_name,
                event_id=i.event_id,
                details=i.details,
                suggested_action=i.suggested_action,
                auto_fixable=i.auto_fixable,
            )
            for i in result.issues_found
        ],
        issues_fixed=[],
        issues_skipped=[],
        errors=result.errors,
    )


@router.get("/pending-deletions")
def get_pending_deletions() -> dict:
    """Get channels pending deletion.

    Returns channels that are past their scheduled delete time.
    """
    from teamarr.database.channels import get_channels_pending_deletion

    with get_db() as conn:
        channels = get_channels_pending_deletion(conn)

    return {
        "count": len(channels),
        "channels": [
            {
                "id": c.id,
                "channel_name": c.channel_name,
                "tvg_id": c.tvg_id,
                "scheduled_delete_at": _safe_isoformat(c.scheduled_delete_at),
                "dispatcharr_channel_id": c.dispatcharr_channel_id,
            }
            for c in channels
        ],
    }


@router.get("/history/{channel_id}")
def get_channel_history(
    channel_id: int,
    limit: int = Query(50, ge=1, le=500, description="Maximum records to return"),
) -> dict:
    """Get history for a managed channel."""
    from teamarr.database.channels import get_channel_history, get_managed_channel

    with get_db() as conn:
        channel = get_managed_channel(conn, channel_id)
        if not channel:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Channel {channel_id} not found",
            )

        history = get_channel_history(conn, channel_id, limit=limit)

    return {
        "channel_id": channel_id,
        "channel_name": channel.channel_name,
        "history": history,
    }


@router.delete("/dispatcharr/{channel_id}", response_model=DeleteResponse)
def delete_dispatcharr_channel(channel_id: int):
    """Delete a channel directly from Dispatcharr by its Dispatcharr ID.

    Use this for orphan_dispatcharr channels that exist in Dispatcharr
    but aren't tracked by Teamarr. This bypasses the managed channels table.
    """
    from teamarr.database.settings import get_dispatcharr_settings
    from teamarr.dispatcharr import get_dispatcharr_client
    from teamarr.dispatcharr.managers.channels import ChannelManager

    with get_db() as conn:
        settings = get_dispatcharr_settings(conn)

    if not settings.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dispatcharr not configured",
        )

    try:
        client = get_dispatcharr_client(get_db)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to connect to Dispatcharr: {e}",
        ) from e

    if not client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dispatcharr connection not available",
        )

    manager = ChannelManager(client)

    # First verify the channel exists
    channel = manager.get_channel(channel_id, use_cache=False)
    if not channel:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Channel {channel_id} not found in Dispatcharr",
        )

    # Delete it
    result = manager.delete_channel(channel_id)

    if result.success:
        return DeleteResponse(
            success=True,
            message=f"Channel '{channel.name}' (ID: {channel_id}) deleted from Dispatcharr",
        )
    else:
        return DeleteResponse(
            success=False,
            message=f"Failed to delete channel: {result.error}",
        )


# =============================================================================
# RESET ALL TEAMARR CHANNELS
# =============================================================================


class ResetChannelInfo(BaseModel):
    """Info about a Teamarr channel in Dispatcharr."""

    dispatcharr_channel_id: int
    uuid: str | None = None
    tvg_id: str
    channel_name: str
    channel_number: str | None = None
    stream_count: int = 0


class ResetPreviewResponse(BaseModel):
    """Response for reset preview."""

    success: bool
    channel_count: int
    channels: list[ResetChannelInfo]


class ResetExecuteResponse(BaseModel):
    """Response for reset execution."""

    success: bool
    deleted_count: int
    error_count: int
    errors: list[str] = Field(default_factory=list)


@router.get("/reset", response_model=ResetPreviewResponse)
def preview_reset_channels():
    """Preview all Teamarr-created channels that would be deleted by reset.

    Returns all channels in Dispatcharr with teamarr-event-* tvg_id,
    regardless of whether they're tracked in managed_channels.
    """
    from teamarr.dispatcharr import ChannelManager, get_dispatcharr_client

    client = get_dispatcharr_client(get_db)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dispatcharr connection not available",
        )

    manager = ChannelManager(client)
    all_channels = manager.get_channels()

    # Find ALL teamarr-event channels
    teamarr_channels = []
    for ch in all_channels:
        tvg_id = ch.tvg_id or ""
        if tvg_id.startswith("teamarr-event-"):
            teamarr_channels.append(
                ResetChannelInfo(
                    dispatcharr_channel_id=ch.id,
                    uuid=ch.uuid,
                    tvg_id=tvg_id,
                    channel_name=ch.name,
                    channel_number=ch.channel_number,
                    stream_count=len(ch.streams) if ch.streams else 0,
                )
            )

    return ResetPreviewResponse(
        success=True,
        channel_count=len(teamarr_channels),
        channels=teamarr_channels,
    )


@router.post("/reset", response_model=ResetExecuteResponse)
def execute_reset_channels():
    """Delete ALL Teamarr-created channels from Dispatcharr.

    This is a destructive operation that removes all channels with
    teamarr-event-* tvg_id. Also marks all managed_channels as deleted.

    Will fail if EPG generation is currently in progress.
    """
    from teamarr.api.generation_status import is_in_progress
    from teamarr.dispatcharr import ChannelManager, get_dispatcharr_client

    # Check if EPG generation is in progress
    if is_in_progress():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot reset channels while EPG generation is in progress",
        )

    client = get_dispatcharr_client(get_db)
    if not client:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Dispatcharr connection not available",
        )

    manager = ChannelManager(client)
    all_channels = manager.get_channels()

    deleted_count = 0
    errors: list[str] = []

    # Find and delete ALL teamarr-event channels
    for ch in all_channels:
        tvg_id = ch.tvg_id or ""
        if not tvg_id.startswith("teamarr-event-"):
            continue

        result = manager.delete_channel(ch.id)
        if result.success:
            deleted_count += 1
        else:
            errors.append(f"Failed to delete {ch.name}: {result.error}")

    # Mark all managed_channels as deleted
    from teamarr.database.channels.crud import mark_all_channels_deleted

    with get_db() as conn:
        mark_all_channels_deleted(conn)

    return ResetExecuteResponse(
        success=len(errors) == 0,
        deleted_count=deleted_count,
        error_count=len(errors),
        errors=errors,
    )
