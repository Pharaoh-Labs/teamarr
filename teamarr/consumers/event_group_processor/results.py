"""Result dataclasses for event-group processing."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ProcessingResult:
    """Result of processing an event group."""

    group_id: int
    group_name: str
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None

    # Stream fetching and filtering
    streams_fetched: int = 0
    streams_after_filter: int = 0  # After all filtering
    filtered_stale: int = 0  # Marked as stale in Dispatcharr
    filtered_not_event: int = 0  # Didn't look like an event (no vs/@/at/date)
    filtered_include_regex: int = 0  # Didn't match include pattern
    filtered_exclude_regex: int = 0  # Matched exclude pattern
    filtered_team: int = 0  # Team not in include/exclude filter

    # Stream matching
    streams_matched: int = 0  # Distinct streams that matched ≥1 event (coverage)
    streams_unmatched: int = 0  # Distinct streams with no match (coverage)
    match_result_count: int = 0  # Total matched results produced (volume; EPG fans out)
    streams_excluded: int = 0  # Matched but excluded by timing (past/final/early)

    # Excluded breakdown by reason
    excluded_event_final: int = 0
    excluded_event_past: int = 0
    excluded_before_window: int = 0
    excluded_league_not_included: int = 0

    # Channel lifecycle
    channels_created: int = 0
    channels_existing: int = 0
    channels_skipped: int = 0
    channels_deleted: int = 0
    channel_errors: int = 0

    # EPG generation
    programmes_generated: int = 0
    events_count: int = 0  # Actual event programmes (excluding filler)
    pregame_count: int = 0  # Pregame filler programmes
    postgame_count: int = 0  # Postgame filler programmes
    xmltv_size: int = 0

    # Errors
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "group_id": self.group_id,
            "group_name": self.group_name,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "streams": {
                "fetched": self.streams_fetched,
                "after_filter": self.streams_after_filter,
                "filtered_stale": self.filtered_stale,
                "filtered_not_event": self.filtered_not_event,
                "filtered_include": self.filtered_include_regex,
                "filtered_exclude": self.filtered_exclude_regex,
                "matched": self.streams_matched,
                "unmatched": self.streams_unmatched,
                "match_results": self.match_result_count,
            },
            "channels": {
                "created": self.channels_created,
                "existing": self.channels_existing,
                "skipped": self.channels_skipped,
                "deleted": self.channels_deleted,
                "errors": self.channel_errors,
            },
            "epg": {
                "programmes": self.programmes_generated,
                "events": self.events_count,
                "pregame": self.pregame_count,
                "postgame": self.postgame_count,
                "xmltv_bytes": self.xmltv_size,
            },
            "errors": self.errors,
        }


@dataclass
class EnforcementStepResult:
    """Outcome of one post-processing enforcement step.

    Replaces the old best-effort try/except-and-log pattern: each step's
    success, affected-item count, and failure detail are recorded so run
    stats can surface them instead of losing failures in warning logs.
    """

    step: str
    ok: bool = True
    count: int = 0  # Items affected (moved/merged/reordered/deleted)
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "step": self.step,
            "ok": self.ok,
            "count": self.count,
            "error": self.error,
        }


@dataclass
class BatchProcessingResult:
    """Result of processing multiple groups."""

    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    results: list[ProcessingResult] = field(default_factory=list)
    total_xmltv: str = ""
    enforcement: list[EnforcementStepResult] = field(default_factory=list)

    @property
    def groups_processed(self) -> int:
        return len(self.results)

    @property
    def total_channels_created(self) -> int:
        return sum(r.channels_created for r in self.results)

    @property
    def total_errors(self) -> int:
        return sum(len(r.errors) for r in self.results)

    @property
    def total_programmes(self) -> int:
        return sum(r.programmes_generated for r in self.results)

    @property
    def total_events(self) -> int:
        """Actual event programmes (excluding filler)."""
        return sum(r.events_count for r in self.results)

    @property
    def total_pregame(self) -> int:
        """Total pregame filler programmes."""
        return sum(r.pregame_count for r in self.results)

    @property
    def total_postgame(self) -> int:
        """Total postgame filler programmes."""
        return sum(r.postgame_count for r in self.results)

    @property
    def total_streams_fetched(self) -> int:
        """Total streams fetched across all groups."""
        return sum(r.streams_fetched for r in self.results)

    @property
    def total_streams_matched(self) -> int:
        """Total streams matched across all groups."""
        return sum(r.streams_matched for r in self.results)

    @property
    def total_streams_unmatched(self) -> int:
        """Total streams unmatched across all groups."""
        return sum(r.streams_unmatched for r in self.results)

    @property
    def total_channels_deleted(self) -> int:
        """Total channels deleted across all groups."""
        return sum(r.channels_deleted for r in self.results)

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "groups_processed": self.groups_processed,
            "total_channels_created": self.total_channels_created,
            "total_errors": self.total_errors,
            "results": [r.to_dict() for r in self.results],
            "enforcement": [s.to_dict() for s in self.enforcement],
        }


@dataclass
class PreviewStream:
    """Individual stream preview result."""

    stream_id: int
    stream_name: str
    matched: bool
    event_id: str | None = None
    event_name: str | None = None
    home_team: str | None = None
    away_team: str | None = None
    league: str | None = None
    start_time: str | None = None
    from_cache: bool = False
    exclusion_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "stream_id": self.stream_id,
            "stream_name": self.stream_name,
            "matched": self.matched,
            "event_id": self.event_id,
            "event_name": self.event_name,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "league": self.league,
            "start_time": self.start_time,
            "from_cache": self.from_cache,
            "exclusion_reason": self.exclusion_reason,
        }


@dataclass
class PreviewResult:
    """Result of previewing stream matches for a group."""

    group_id: int
    group_name: str

    # Totals
    total_streams: int = 0
    filtered_count: int = 0
    matched_count: int = 0
    unmatched_count: int = 0

    # Filter breakdown
    filtered_stale: int = 0
    filtered_not_event: int = 0
    filtered_include_regex: int = 0
    filtered_exclude_regex: int = 0

    # Cache stats
    cache_hits: int = 0
    cache_misses: int = 0

    # Stream details
    streams: list[PreviewStream] = field(default_factory=list)

    # Errors
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "group_id": self.group_id,
            "group_name": self.group_name,
            "total_streams": self.total_streams,
            "filtered_count": self.filtered_count,
            "matched_count": self.matched_count,
            "unmatched_count": self.unmatched_count,
            "filtered_stale": self.filtered_stale,
            "filtered_not_event": self.filtered_not_event,
            "filtered_include_regex": self.filtered_include_regex,
            "filtered_exclude_regex": self.filtered_exclude_regex,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "streams": [s.to_dict() for s in self.streams],
            "errors": self.errors,
        }
