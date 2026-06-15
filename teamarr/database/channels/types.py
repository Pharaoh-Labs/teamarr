"""Channel database types and dataclasses.

Data types for managed channels, streams, and exception keywords.
"""

import json
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ManagedChannel:
    """A managed channel owned by an event.

    Channel identity: (event_id, event_provider, exception_keyword, primary_stream_id).
    The event_epg_group_id tracks which source group supplied the first stream (provenance).
    """

    id: int
    event_epg_group_id: int | None  # Source group (provenance, not ownership)
    event_id: str
    event_provider: str
    tvg_id: str
    channel_name: str
    channel_number: str | None = None
    logo_url: str | None = None

    # Dispatcharr integration
    dispatcharr_channel_id: int | None = None
    dispatcharr_uuid: str | None = None
    dispatcharr_logo_id: int | None = None

    # Channel settings
    channel_group_id: int | None = None
    channel_profile_ids: list[int] = field(default_factory=list)
    primary_stream_id: int | None = None
    exception_keyword: str | None = None
    feed_team_id: str | None = None

    # Event context
    home_team: str | None = None
    away_team: str | None = None
    event_date: datetime | None = None
    event_name: str | None = None
    league: str | None = None
    sport: str | None = None

    # Lifecycle
    scheduled_delete_at: datetime | None = None
    deleted_at: datetime | None = None
    delete_reason: str | None = None

    # Sync status
    sync_status: str = "pending"
    sync_message: str | None = None
    last_verified_at: datetime | None = None

    # Timestamps
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict) -> "ManagedChannel":
        """Create from database row dict."""
        profile_ids = row.get("channel_profile_ids")
        if profile_ids and isinstance(profile_ids, str):
            try:
                profile_ids = json.loads(profile_ids)
            except json.JSONDecodeError:
                profile_ids = []

        return cls(
            id=row["id"],
            event_epg_group_id=row.get("event_epg_group_id"),
            event_id=row["event_id"],
            event_provider=row["event_provider"],
            tvg_id=row["tvg_id"],
            channel_name=row["channel_name"],
            channel_number=row.get("channel_number"),
            logo_url=row.get("logo_url"),
            dispatcharr_channel_id=row.get("dispatcharr_channel_id"),
            dispatcharr_uuid=row.get("dispatcharr_uuid"),
            dispatcharr_logo_id=row.get("dispatcharr_logo_id"),
            channel_group_id=row.get("channel_group_id"),
            channel_profile_ids=profile_ids or [],
            primary_stream_id=row.get("primary_stream_id"),
            exception_keyword=row.get("exception_keyword"),
            feed_team_id=row.get("feed_team_id"),
            home_team=row.get("home_team"),
            away_team=row.get("away_team"),
            event_date=row.get("event_date"),
            event_name=row.get("event_name"),
            league=row.get("league"),
            sport=row.get("sport"),
            scheduled_delete_at=row.get("scheduled_delete_at"),
            deleted_at=row.get("deleted_at"),
            delete_reason=row.get("delete_reason"),
            sync_status=row.get("sync_status", "pending"),
            sync_message=row.get("sync_message"),
            last_verified_at=row.get("last_verified_at"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )


@dataclass
class ManagedChannelStream:
    """A stream attached to a managed channel."""

    id: int
    managed_channel_id: int
    dispatcharr_stream_id: int
    stream_name: str | None = None
    source_group_id: int | None = None
    source_group_type: str = "parent"
    priority: int = 0
    m3u_account_id: int | None = None
    m3u_account_name: str | None = None
    exception_keyword: str | None = None
    match_type: str = "event"
    match_method: str | None = None  # 'epg', 'fuzzy', etc. — drives the epg_match ordering rule
    # DP channel's own group name (channel-source streams) — drives the
    # dispatcharr_group ordering rule (ybt.3). NULL for non-channel-source streams.
    dispatcharr_channel_group: str | None = None
    added_at: datetime | None = None
    removed_at: datetime | None = None
    # Time-windowed membership (epic teamarrv2-183.5). NULL = full-life.
    attach_at: datetime | None = None
    detach_at: datetime | None = None
    # Stream stats cached from Dispatcharr (video codec, resolution, bitrate, fps, etc.)
    stream_stats: dict | None = None
    stream_stats_updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict) -> "ManagedChannelStream":
        """Create from database row dict."""
        import json as _json
        raw_stats = row.get("stream_stats")
        stream_stats = None
        if isinstance(raw_stats, str):
            try:
                stream_stats = _json.loads(raw_stats)
            except Exception:
                stream_stats = None
        elif isinstance(raw_stats, dict):
            stream_stats = raw_stats
        return cls(
            id=row["id"],
            managed_channel_id=row["managed_channel_id"],
            dispatcharr_stream_id=row["dispatcharr_stream_id"],
            stream_name=row.get("stream_name"),
            source_group_id=row.get("source_group_id"),
            source_group_type=row.get("source_group_type", "parent"),
            priority=row.get("priority", 0),
            m3u_account_id=row.get("m3u_account_id"),
            m3u_account_name=row.get("m3u_account_name"),
            exception_keyword=row.get("exception_keyword"),
            match_type=row.get("match_type", "event"),
            match_method=row.get("match_method"),
            dispatcharr_channel_group=row.get("dispatcharr_channel_group"),
            added_at=row.get("added_at"),
            removed_at=row.get("removed_at"),
            attach_at=row.get("attach_at"),
            detach_at=row.get("detach_at"),
            stream_stats=stream_stats,
            stream_stats_updated_at=row.get("stream_stats_updated_at"),
        )
