"""Event Group Processor - orchestrates the full event-based EPG flow.

Connects stream matching to channel lifecycle:
1. Load group config from database
2. Fetch M3U streams from Dispatcharr
3. Fetch events from data providers
4. Match streams to events
5. Create/update channels via ChannelLifecycleService
6. Generate XMLTV EPG
7. Optionally push EPG to Dispatcharr

This is the main entry point for event-based EPG generation.
"""

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from sqlite3 import Connection
from typing import Any

from teamarr.consumers.channel_lifecycle import (
    StreamProcessResult,
    create_lifecycle_service,
)
from teamarr.consumers.event_epg import EventEPGGenerator
from teamarr.consumers.multi_league_matcher import BatchMatchResult, MultiLeagueMatcher
from teamarr.core import Event
from teamarr.database.groups import EventEPGGroup, get_all_groups, get_group
from teamarr.services import SportsDataService, create_default_service

logger = logging.getLogger(__name__)


@dataclass
class ProcessingResult:
    """Result of processing an event group."""

    group_id: int
    group_name: str
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None

    # Stream matching
    streams_fetched: int = 0
    streams_matched: int = 0
    streams_unmatched: int = 0

    # Channel lifecycle
    channels_created: int = 0
    channels_existing: int = 0
    channels_skipped: int = 0
    channels_deleted: int = 0
    channel_errors: int = 0

    # EPG generation
    programmes_generated: int = 0
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
                "matched": self.streams_matched,
                "unmatched": self.streams_unmatched,
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
                "xmltv_bytes": self.xmltv_size,
            },
            "errors": self.errors,
        }


@dataclass
class BatchProcessingResult:
    """Result of processing multiple groups."""

    started_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    results: list[ProcessingResult] = field(default_factory=list)
    total_xmltv: str = ""

    @property
    def groups_processed(self) -> int:
        return len(self.results)

    @property
    def total_channels_created(self) -> int:
        return sum(r.channels_created for r in self.results)

    @property
    def total_errors(self) -> int:
        return sum(len(r.errors) for r in self.results)

    def to_dict(self) -> dict:
        """Convert to dict for JSON serialization."""
        return {
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "groups_processed": self.groups_processed,
            "total_channels_created": self.total_channels_created,
            "total_errors": self.total_errors,
            "results": [r.to_dict() for r in self.results],
        }


class EventGroupProcessor:
    """Processes event groups - matches streams to events and manages channels.

    Usage:
        from teamarr.database import get_db
        from teamarr.dispatcharr import get_factory

        factory = get_factory(get_db)
        client = factory.get_client()

        processor = EventGroupProcessor(
            db_factory=get_db,
            dispatcharr_client=client,
        )

        # Process a single group
        result = processor.process_group(group_id=1)

        # Process all active groups
        result = processor.process_all_groups()
    """

    def __init__(
        self,
        db_factory: Any,
        dispatcharr_client: Any = None,
        service: SportsDataService | None = None,
    ):
        """Initialize the processor.

        Args:
            db_factory: Factory function returning database connection
            dispatcharr_client: Optional DispatcharrClient for Dispatcharr operations
            service: Optional SportsDataService (creates default if not provided)
        """
        self._db_factory = db_factory
        self._dispatcharr_client = dispatcharr_client
        self._service = service or create_default_service()

        # EPG generator for XMLTV output
        self._epg_generator = EventEPGGenerator(self._service)

    def process_group(
        self,
        group_id: int,
        target_date: date | None = None,
    ) -> ProcessingResult:
        """Process a single event group.

        Args:
            group_id: Group ID to process
            target_date: Target date (defaults to today)

        Returns:
            ProcessingResult with all details
        """
        target_date = target_date or date.today()

        with self._db_factory() as conn:
            group = get_group(conn, group_id)
            if not group:
                result = ProcessingResult(group_id=group_id, group_name="Unknown")
                result.errors.append(f"Group {group_id} not found")
                result.completed_at = datetime.now()
                return result

            return self._process_group_internal(conn, group, target_date)

    def process_all_groups(
        self,
        target_date: date | None = None,
    ) -> BatchProcessingResult:
        """Process all active event groups.

        Args:
            target_date: Target date (defaults to today)

        Returns:
            BatchProcessingResult with all group results
        """
        target_date = target_date or date.today()
        batch_result = BatchProcessingResult()

        with self._db_factory() as conn:
            groups = get_all_groups(conn, include_inactive=False)

            for group in groups:
                result = self._process_group_internal(conn, group, target_date)
                batch_result.results.append(result)

                # TODO: Collect programmes for combined XMLTV

        batch_result.completed_at = datetime.now()
        return batch_result

    def _process_group_internal(
        self,
        conn: Connection,
        group: EventEPGGroup,
        target_date: date,
    ) -> ProcessingResult:
        """Internal processing for a single group."""
        result = ProcessingResult(group_id=group.id, group_name=group.name)

        try:
            # Step 1: Fetch M3U streams from Dispatcharr
            streams = self._fetch_streams(group)
            result.streams_fetched = len(streams)

            if not streams:
                result.errors.append("No streams found for group")
                result.completed_at = datetime.now()
                return result

            # Step 2: Fetch events from data providers
            events = self._fetch_events(group.leagues, target_date)

            if not events:
                result.errors.append(f"No events found for leagues: {group.leagues}")
                result.completed_at = datetime.now()
                return result

            # Step 3: Match streams to events
            match_result = self._match_streams(streams, group.leagues, target_date)
            result.streams_matched = match_result.matched_count
            result.streams_unmatched = match_result.unmatched_count

            # Step 4: Create/update channels
            matched_streams = self._build_matched_stream_list(streams, match_result)
            if matched_streams:
                lifecycle_result = self._process_channels(matched_streams, group, conn)
                result.channels_created = len(lifecycle_result.created)
                result.channels_existing = len(lifecycle_result.existing)
                result.channels_skipped = len(lifecycle_result.skipped)
                result.channel_errors = len(lifecycle_result.errors)

                for error in lifecycle_result.errors:
                    result.errors.append(f"Channel error: {error}")

            # Step 5: Generate XMLTV (from matched events)
            # TODO: Generate XMLTV from managed channels

        except Exception as e:
            logger.exception(f"Error processing group {group.name}")
            result.errors.append(str(e))

        result.completed_at = datetime.now()
        return result

    def _fetch_streams(self, group: EventEPGGroup) -> list[dict]:
        """Fetch M3U streams from Dispatcharr for the group.

        Uses group's m3u_group_id to filter streams.
        """
        if not self._dispatcharr_client:
            logger.warning("Dispatcharr not configured - cannot fetch streams")
            return []

        try:
            from teamarr.dispatcharr import M3UManager

            m3u_manager = M3UManager(self._dispatcharr_client)

            # Fetch streams filtered by M3U group if configured
            if group.m3u_group_id:
                streams = m3u_manager.list_streams(group_id=group.m3u_group_id)
            else:
                # Fetch all streams if no group filter
                streams = m3u_manager.list_streams()

            # Convert to dicts for matcher
            return [
                {
                    "id": s.id,
                    "name": s.name,
                    "tvg_id": s.tvg_id,
                    "tvg_name": s.tvg_name,
                    "channel_group": s.channel_group,
                    "channel_group_id": s.channel_group_id,
                    "m3u_account_id": s.m3u_account_id,
                }
                for s in streams
            ]

        except Exception as e:
            logger.error(f"Failed to fetch streams: {e}")
            return []

    def _fetch_events(self, leagues: list[str], target_date: date) -> list[Event]:
        """Fetch events from data providers for leagues."""
        all_events: list[Event] = []

        for league in leagues:
            try:
                events = self._service.get_events(league, target_date)
                all_events.extend(events)
            except Exception as e:
                logger.warning(f"Failed to fetch events for {league}: {e}")

        return all_events

    def _match_streams(
        self,
        streams: list[dict],
        leagues: list[str],
        target_date: date,
    ) -> BatchMatchResult:
        """Match streams to events using MultiLeagueMatcher."""
        matcher = MultiLeagueMatcher(
            service=self._service,
            search_leagues=leagues,
            include_leagues=leagues,
        )

        stream_names = [s["name"] for s in streams]
        return matcher.match_all(stream_names, target_date)

    def _build_matched_stream_list(
        self,
        streams: list[dict],
        match_result: BatchMatchResult,
    ) -> list[dict]:
        """Build list of matched streams with their events.

        Returns list of dicts with 'stream' and 'event' keys.
        """
        # Build name -> stream lookup
        stream_lookup = {s["name"]: s for s in streams}

        matched = []
        for result in match_result.results:
            if result.matched and result.included and result.event:
                stream = stream_lookup.get(result.stream_name)
                if stream:
                    matched.append(
                        {
                            "stream": stream,
                            "event": result.event,
                        }
                    )

        return matched

    def _process_channels(
        self,
        matched_streams: list[dict],
        group: EventEPGGroup,
        conn: Connection,
    ) -> StreamProcessResult:
        """Create/update channels via ChannelLifecycleService."""
        lifecycle_service = create_lifecycle_service(
            self._db_factory,
            self._dispatcharr_client,
        )

        # Build group config dict
        group_config = {
            "id": group.id,
            "duplicate_event_handling": group.duplicate_event_handling,
            "channel_group_id": group.channel_group_id,
            "stream_profile_id": group.stream_profile_id,
            "channel_profile_ids": group.channel_profile_ids,
            "channel_start_number": group.channel_start_number,
        }

        # TODO: Load template if group has one
        template = None

        return lifecycle_service.process_matched_streams(matched_streams, group_config, template)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================


def process_event_group(
    db_factory: Any,
    group_id: int,
    dispatcharr_client: Any = None,
    target_date: date | None = None,
) -> ProcessingResult:
    """Process a single event group.

    Convenience function that creates a processor and runs it.

    Args:
        db_factory: Factory function returning database connection
        group_id: Group ID to process
        dispatcharr_client: Optional DispatcharrClient
        target_date: Target date (defaults to today)

    Returns:
        ProcessingResult
    """
    processor = EventGroupProcessor(
        db_factory=db_factory,
        dispatcharr_client=dispatcharr_client,
    )
    return processor.process_group(group_id, target_date)


def process_all_event_groups(
    db_factory: Any,
    dispatcharr_client: Any = None,
    target_date: date | None = None,
) -> BatchProcessingResult:
    """Process all active event groups.

    Convenience function that creates a processor and runs it.

    Args:
        db_factory: Factory function returning database connection
        dispatcharr_client: Optional DispatcharrClient
        target_date: Target date (defaults to today)

    Returns:
        BatchProcessingResult
    """
    processor = EventGroupProcessor(
        db_factory=db_factory,
        dispatcharr_client=dispatcharr_client,
    )
    return processor.process_all_groups(target_date)
