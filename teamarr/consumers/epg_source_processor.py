"""EPG source processor for the generation pipeline.

Fetches external XMLTV feeds, matches programmes to sports API events,
and creates channels using the existing lifecycle service.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from teamarr.consumers.epg_source_matcher import EPGProgrammeMatcher
from teamarr.database.epg_sources.connection import get_epg_sources_db, DEFAULT_DB_PATH
from teamarr.database.epg_sources import crud as epg_crud
from teamarr.services import SportsDataService
from teamarr.utilities.xmltv_parser import fetch_and_parse_source

logger = logging.getLogger(__name__)


@dataclass
class EPGSourceResult:
    """Result of EPG source processing."""

    sources_processed: int = 0
    mappings_processed: int = 0
    programmes_scanned: int = 0
    programmes_matched: int = 0
    channels_created: int = 0
    channels_existing: int = 0
    errors: list[str] = field(default_factory=list)


class EPGSourceProcessor:
    """Processes external EPG sources during generation."""

    def __init__(
        self,
        db_factory: Callable,
        service: SportsDataService,
        dispatcharr_client: Any | None = None,
    ):
        self._db_factory = db_factory
        self._service = service
        self._dispatcharr_client = dispatcharr_client

    def process_all(
        self,
        progress_callback: Callable | None = None,
    ) -> EPGSourceResult:
        """Process all enabled EPG source mappings."""
        result = EPGSourceResult()

        if not DEFAULT_DB_PATH.exists():
            return result

        try:
            with get_epg_sources_db() as epg_conn:
                sources = epg_crud.list_sources(epg_conn, include_disabled=False)
                if not sources:
                    return result

                mappings = epg_crud.list_mappings(epg_conn, enabled_only=True)
                if not mappings:
                    return result
        except Exception as e:
            logger.warning("[EPG_SOURCES] Failed to load EPG sources: %s", e)
            return result

        # Group mappings by source for efficient fetching
        source_map = {s["id"]: s for s in sources}
        mappings_by_source: dict[int, list[dict]] = {}
        for m in mappings:
            sid = m["source_id"]
            if sid in source_map:
                mappings_by_source.setdefault(sid, []).append(m)

        # Get search leagues from subscription
        search_leagues = self._get_search_leagues()
        if not search_leagues:
            logger.info("[EPG_SOURCES] No leagues configured, skipping")
            return result

        matcher = EPGProgrammeMatcher(
            service=self._service,
            search_leagues=search_leagues,
        )

        for source_id, source_mappings in mappings_by_source.items():
            source = source_map[source_id]
            result.sources_processed += 1

            try:
                self._process_source(
                    source, source_mappings, matcher, result
                )
            except Exception as e:
                err_msg = f"Error processing source '{source['name']}': {e}"
                logger.error("[EPG_SOURCES] %s", err_msg)
                result.errors.append(err_msg)

        return result

    def _process_source(
        self,
        source: dict,
        mappings: list[dict],
        matcher: EPGProgrammeMatcher,
        result: EPGSourceResult,
    ) -> None:
        """Process a single EPG source: fetch, parse, match, create channels."""
        source_id = source["id"]
        url = source["url"]
        logger.info("[EPG_SOURCES] Fetching source '%s' from %s", source["name"], url)

        try:
            channels, programmes = fetch_and_parse_source(url)
        except Exception as e:
            with get_epg_sources_db() as epg_conn:
                epg_crud.update_source_fetch_status(
                    epg_conn, source_id, "error", str(e)
                )
            raise

        # Update channels and programmes in EPG sources DB
        with get_epg_sources_db() as epg_conn:
            epg_crud.upsert_channels(epg_conn, source_id, channels)

            channel_rows = epg_crud.list_channels(epg_conn, source_id)
            xmltv_to_db_id = {
                c["channel_xmltv_id"]: c["id"] for c in channel_rows
            }

            # Store programmes per channel
            total_progs = 0
            for ch_xmltv_id, db_id in xmltv_to_db_id.items():
                ch_progs = [
                    p for p in programmes if p["channel_xmltv_id"] == ch_xmltv_id
                ]
                if ch_progs:
                    epg_crud.replace_programmes(epg_conn, db_id, ch_progs)
                    total_progs += len(ch_progs)

            epg_crud.update_source_fetch_status(
                epg_conn, source_id, "success",
                channel_count=len(channels),
                programme_count=total_progs,
            )

        # Now match programmes for each mapping
        for mapping in mappings:
            result.mappings_processed += 1
            try:
                self._process_mapping(mapping, matcher, result)
            except Exception as e:
                err_msg = (
                    f"Error processing mapping {mapping['id']} "
                    f"({mapping.get('epg_channel_name', '?')}): {e}"
                )
                logger.error("[EPG_SOURCES] %s", err_msg)
                result.errors.append(err_msg)

    def _process_mapping(
        self,
        mapping: dict,
        matcher: EPGProgrammeMatcher,
        result: EPGSourceResult,
    ) -> None:
        """Process a single stream mapping: match programmes, create channels."""
        epg_channel_id = mapping["epg_channel_id"]
        mapping_id = mapping["id"]
        stream_id = mapping["dispatcharr_stream_id"]
        stream_name = mapping.get("dispatcharr_stream_name", "")

        # Get programmes for this EPG channel
        with get_epg_sources_db() as epg_conn:
            programmes = epg_crud.list_programmes(epg_conn, epg_channel_id)
            # Clear previous managed channels for this mapping
            epg_crud.clear_managed_channels(epg_conn, mapping_id)

        if not programmes:
            return

        # Filter to today + upcoming (next 3 days)
        from datetime import datetime, timedelta, timezone

        now = datetime.now(timezone.utc)
        cutoff = now + timedelta(days=3)
        upcoming = [
            p for p in programmes
            if self._parse_time(p.get("start_time")) and
            self._parse_time(p["start_time"]) >= now - timedelta(hours=6) and
            self._parse_time(p["start_time"]) <= cutoff
        ]

        result.programmes_scanned += len(upcoming)

        # Match each programme
        matched_streams = []
        for prog in upcoming:
            event = matcher.match_programme({
                "title": prog["title"],
                "start": prog["start_time"],
                "stop": prog["stop_time"],
                "description": prog.get("description"),
            })
            if event:
                result.programmes_matched += 1
                matched_streams.append({
                    "stream": {"id": stream_id, "name": stream_name},
                    "event": event,
                })

                # Record in EPG sources DB
                with get_epg_sources_db() as epg_conn:
                    epg_crud.record_managed_channel(
                        epg_conn,
                        mapping_id=mapping_id,
                        event_id=event.id,
                        event_provider=event.provider,
                        programme_title=prog["title"],
                        programme_start=prog["start_time"],
                        programme_stop=prog["stop_time"],
                    )

        if not matched_streams:
            return

        # Create channels via existing lifecycle service
        try:
            from teamarr.consumers.channel_lifecycle import create_lifecycle_service

            lifecycle_service = create_lifecycle_service(
                self._db_factory,
                self._service,
                self._dispatcharr_client,
            )
            lifecycle_service.compute_external_occupied()

            group_config = {
                "id": None,
                "m3u_account_id": mapping.get("m3u_account_id"),
                "m3u_account_name": None,
            }

            process_result = lifecycle_service.process_matched_streams(
                matched_streams, group_config
            )
            result.channels_created += len(process_result.created)
            result.channels_existing += len(process_result.existing)

        except Exception as e:
            logger.error(
                "[EPG_SOURCES] Channel creation failed for mapping %d: %s",
                mapping_id, e,
            )
            result.errors.append(f"Channel creation error: {e}")

    def _get_search_leagues(self) -> list[str]:
        """Get leagues to search from subscription settings."""
        try:
            from teamarr.database.subscription import get_subscription

            with self._db_factory() as conn:
                sub = get_subscription(conn)
                return sub.leagues or []
        except Exception:
            return []

    @staticmethod
    def _parse_time(time_str: str | None):
        if not time_str:
            return None
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(time_str)
            if dt.tzinfo is None:
                from datetime import timezone
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return None
