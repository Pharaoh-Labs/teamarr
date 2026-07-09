"""Preview path — match a group's streams without channel/EPG side effects."""

import logging
from datetime import date
from typing import TYPE_CHECKING, Any

from teamarr.database.groups import get_group
from teamarr.utilities.sorting import natural_sort_key

from .results import PreviewResult, PreviewStream

logger = logging.getLogger(__name__)


class PreviewBuilder:
    """Runs the matching pipeline for preview, skipping all side effects.

    Mixin for EventGroupProcessor.
    """

    if TYPE_CHECKING:
        # Provided by the EventGroupProcessor coordinator / sibling mixins.
        # Declared for type-checkers only — no runtime effect.
        _db_factory: Any
        _dispatcharr_client: Any
        _filter_streams: Any
        _get_subscription_leagues: Any
        _match_streams: Any

    def preview_group(
        self,
        group_id: int,
        target_date: date | None = None,
    ) -> PreviewResult:
        """Preview stream matching for a group without creating channels.

        Performs all matching logic but skips channel creation and EPG generation.
        Used for testing and previewing before actual processing.

        Args:
            group_id: Group ID to preview
            target_date: Target date (defaults to today)

        Returns:
            PreviewResult with stream matching details
        """
        target_date = target_date or date.today()

        with self._db_factory() as conn:
            group = get_group(conn, group_id)
            if not group:
                result = PreviewResult(group_id=group_id, group_name="Unknown")
                result.errors.append(f"Group {group_id} not found")
                return result

            result = PreviewResult(group_id=group_id, group_name=group.name)

            # Step 0: Refresh M3U account before fetching streams (skip if recent)
            if not self._dispatcharr_client:
                result.errors.append("Dispatcharr not configured")
                return result

            if group.m3u_account_id:
                try:
                    refresh_result = self._dispatcharr_client.m3u.wait_for_refresh(
                        group.m3u_account_id,
                        timeout=180,
                        skip_if_recent_minutes=60,
                    )
                    if refresh_result.skipped:
                        logger.debug(
                            f"Preview: M3U account {group.m3u_account_id} "
                            "recently refreshed, skipping"
                        )
                    elif refresh_result.success:
                        logger.debug(
                            f"Preview: M3U account {group.m3u_account_id} "
                            f"refreshed in {refresh_result.duration:.1f}s"
                        )
                    else:
                        logger.warning(
                            f"Preview: M3U refresh failed: {refresh_result.message} "
                            "- continuing with potentially stale data"
                        )
                except Exception as e:
                    logger.warning(
                        "[EVENT_EPG] Preview: M3U refresh error: %s - continuing anyway", e
                    )

            # Step 1: Fetch streams from M3U group
            try:
                raw_streams = self._dispatcharr_client.m3u.list_streams(
                    group_id=group.m3u_group_id,
                    account_id=group.m3u_account_id,
                )
            except Exception as e:
                result.errors.append(f"Failed to fetch streams: {e}")
                return result

            if not raw_streams:
                result.errors.append("No streams found in M3U group")
                return result

            # Convert DispatcharrStream objects to dict format. Carry tvg_id so
            # EPG program matching (which resolves stream -> channel -> programs)
            # is exercised in preview exactly as in a real generation run.
            streams = [
                {"id": s.id, "name": s.name, "tvg_id": s.tvg_id}
                for s in raw_streams
            ]
            result.total_streams = len(streams)

            # Step 2: Apply stream filtering
            streams, filter_result = self._filter_streams(streams, group)
            result.filtered_count = result.total_streams - filter_result.passed_count
            result.filtered_stale = filter_result.filtered_stale
            # Combine all built-in eligibility filters into filtered_not_event
            result.filtered_not_event = (
                filter_result.filtered_not_event
                + filter_result.filtered_placeholder
                + filter_result.filtered_unsupported_sport
            )
            result.filtered_include_regex = filter_result.filtered_include
            result.filtered_exclude_regex = filter_result.filtered_exclude

            if not streams:
                result.errors.append("All streams filtered out")
                return result

            # Step 3: Match streams to events
            with self._db_factory() as preview_conn:
                effective_leagues = self._get_subscription_leagues(preview_conn, group)
            match_result = self._match_streams(
                streams, group, target_date, resolved_leagues=effective_leagues
            )
            # Coverage (distinct streams) so matched + unmatched relates to total streams,
            # rather than result count which fans out under EPG/TEAM_ONLY matching.
            result.matched_count = match_result.matched_stream_count
            result.unmatched_count = match_result.unmatched_stream_count
            result.cache_hits = match_result.cache_hits
            result.cache_misses = match_result.cache_misses

            # Build preview stream list
            for r in match_result.results:
                stream_id = r.stream_id if hasattr(r, "stream_id") else 0
                stream_name = r.stream_name

                preview_stream = PreviewStream(
                    stream_id=stream_id,
                    stream_name=stream_name,
                    matched=r.matched,
                    event_id=r.event.id if r.event else None,
                    event_name=r.event.name if r.event else None,
                    home_team=r.event.home_team.name if r.event else None,
                    away_team=r.event.away_team.name if r.event else None,
                    league=r.league,
                    start_time=(
                        r.event.start_time.isoformat()
                        if r.event and r.event.start_time
                        else None
                    ),
                    from_cache=getattr(r, "from_cache", False),
                    exclusion_reason=r.exclusion_reason,
                )
                result.streams.append(preview_stream)

            # Sort: matched first, then unmatched; within each, natural sort by name

            result.streams.sort(
                key=lambda s: (not s.matched, natural_sort_key(s.stream_name)),
            )

            return result
