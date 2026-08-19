"""Matched/failed stream persistence for run analysis."""

import logging
from sqlite3 import Connection

from teamarr.consumers.matching import BatchMatchResult
from teamarr.database.stats import (
    FailedMatch,
    MatchedStream,
    save_failed_matches,
    save_matched_streams,
)
from teamarr.services.stream_filter import FilterResult

logger = logging.getLogger(__name__)


class MatchPersistence:
    """Saves per-stream match outcomes to the stats tables.

    Mixin for EventGroupProcessor.
    """

    def _save_match_details(
        self,
        conn: Connection,
        run_id: int,
        group_id: int,
        group_name: str,
        streams: list[dict],
        match_result: BatchMatchResult,
        filter_result: FilterResult | None = None,
    ) -> None:
        """Save detailed match results to database.

        Stores both matched streams and failed/unmatched streams for analysis.
        """
        # ID-first lookup: identically named streams collapse in a name-keyed
        # dict (#264), which would misattribute details to one stream ID.
        stream_by_id = {s["id"]: s for s in streams if s.get("id") is not None}
        stream_by_name = {s["name"]: s for s in streams}

        matched_list: list[MatchedStream] = []
        failed_list: list[FailedMatch] = []

        for result in match_result.results:
            stream = stream_by_id.get(result.stream_id) or stream_by_name.get(
                result.stream_name, {}
            )
            stream_id = stream.get("id")

            if result.matched and result.included and result.event:
                # Successfully matched and included
                event_date = (
                    result.event.start_time.isoformat() if result.event.start_time else None
                )
                # Extract match method and confidence if available (Phase 7 enhancement)
                match_method = getattr(result, "match_method", None)
                if match_method and hasattr(match_method, "value"):
                    match_method = match_method.value  # Convert enum to string
                confidence = getattr(result, "confidence", None)
                origin_method = getattr(result, "origin_match_method", None)
                if origin_method and hasattr(origin_method, "value"):
                    origin_method = origin_method.value  # Convert enum to string

                matched_list.append(
                    MatchedStream(
                        run_id=run_id,
                        group_id=group_id,
                        group_name=group_name,
                        stream_id=stream_id,
                        stream_name=result.stream_name,
                        event_id=result.event.id,
                        event_name=result.event.name,
                        event_date=event_date,
                        detected_league=result.league,
                        home_team=result.event.home_team.name if result.event.home_team else None,
                        away_team=result.event.away_team.name if result.event.away_team else None,
                        from_cache=getattr(result, "from_cache", False),
                        match_method=match_method,
                        confidence=confidence,
                        origin_match_method=origin_method,
                        feed_hint=getattr(result, "feed_hint", None),
                    )
                )
            elif result.matched and not result.included:
                # Matched but excluded (wrong league) - still counts as a match
                event_date = None
                if result.event and result.event.start_time:
                    event_date = result.event.start_time.strftime("%Y-%m-%d %H:%M")
                match_method = getattr(result, "match_method", None)
                if match_method and hasattr(match_method, "value"):
                    match_method = match_method.value  # Convert enum to string
                confidence = getattr(result, "confidence", None)
                origin_method = getattr(result, "origin_match_method", None)
                if origin_method and hasattr(origin_method, "value"):
                    origin_method = origin_method.value  # Convert enum to string

                matched_list.append(
                    MatchedStream(
                        run_id=run_id,
                        group_id=group_id,
                        group_name=group_name,
                        stream_id=stream_id,
                        stream_name=result.stream_name,
                        event_id=result.event.id if result.event else "",
                        event_name=result.event.name if result.event else None,
                        event_date=event_date,
                        detected_league=result.league,
                        home_team=result.event.home_team.name
                        if result.event and result.event.home_team
                        else None,
                        away_team=result.event.away_team.name
                        if result.event and result.event.away_team
                        else None,
                        from_cache=getattr(result, "from_cache", False),
                        excluded=True,
                        exclusion_reason=result.exclusion_reason or "excluded_league",
                        match_method=match_method,
                        confidence=confidence,
                        origin_match_method=origin_method,
                        feed_hint=getattr(result, "feed_hint", None),
                    )
                )
            elif result.is_exception:
                # Exception keyword stream
                failed_list.append(
                    FailedMatch(
                        run_id=run_id,
                        group_id=group_id,
                        group_name=group_name,
                        stream_id=stream_id,
                        stream_name=result.stream_name,
                        reason="exception",
                        detail=f"Keyword: {result.exception_keyword}",
                    )
                )
            else:
                # Skip filtered streams (placeholder, sport_not_supported, etc.)
                # These are expected exclusions, not match failures
                if result.exclusion_reason and result.exclusion_reason.startswith(
                    ("placeholder", "sport_not_supported")
                ):
                    continue

                # Unmatched - extract parsed teams if available (Phase 7 enhancement)
                parsed_team1 = getattr(result, "parsed_team1", None)
                parsed_team2 = getattr(result, "parsed_team2", None)
                detected_league = getattr(result, "detected_league", None)

                # Get detailed failure reason if available
                failed_reason = "unmatched"
                if result.failed_reason:
                    failed_reason = result.failed_reason.value

                failed_list.append(
                    FailedMatch(
                        run_id=run_id,
                        group_id=group_id,
                        group_name=group_name,
                        stream_id=stream_id,
                        stream_name=result.stream_name,
                        reason=failed_reason,
                        parsed_team1=parsed_team1,
                        parsed_team2=parsed_team2,
                        detected_league=detected_league,
                    )
                )

        # Save to database
        if matched_list:
            save_matched_streams(conn, matched_list)
            logger.debug(
                "[EVENT_EPG] Saved %d matched streams for group %s", len(matched_list), group_name
            )

        if failed_list:
            save_failed_matches(conn, failed_list)
            logger.debug(
                "[EVENT_EPG] Saved %d failed matches for group %s", len(failed_list), group_name
            )
