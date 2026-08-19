"""UFC event parsing for ESPN provider.

Pure parsing layer - converts raw ESPN API responses into Event objects.
No API calls, no date filtering - that's the provider's responsibility.
"""

import logging
from typing import TYPE_CHECKING, Any

from teamarr.core import Bout, Event, EventStatus, Team

logger = logging.getLogger(__name__)


class UFCParserMixin:
    """Mixin providing UFC-specific parsing methods.

    Pure parsing only - no API calls or business logic.

    Requires:
        - self.name: Provider name ('espn')
        - self._parse_datetime(date_str): Parse datetime from string
    """

    if TYPE_CHECKING:
        # Provided by the host provider class (ESPNProvider).
        from datetime import datetime

        name: str

        def _parse_datetime(self, date_str: str) -> "datetime | None": ...

    def _parse_ufc_events(self, data: dict) -> list[Event]:
        """Parse UFC scoreboard response into Event objects.

        Pure parsing - no filtering, no API calls.

        Args:
            data: Raw ESPN scoreboard response

        Returns:
            List of parsed Event objects
        """
        if not data:
            return []

        events = []
        for event_data in data.get("events", []):
            event = self._parse_ufc_event(event_data)
            if event:
                events.append(event)

        return events

    def _parse_ufc_event(self, data: dict) -> Event | None:
        """Parse UFC fight card into Event.

        Maps the main event fighters as home_team/away_team for compatibility.
        Extracts exact segment times from ESPN bout-level data:
        - 3 distinct times: early_prelims, prelims, main_card (PPV events)
        - 2 distinct times: prelims, main_card (Fight Night events)
        - 1 time: main_card only

        Also extracts all bouts on the card with their segment assignments.
        """
        try:
            event_id = str(data.get("id", ""))
            if not event_id:
                return None

            competitions = data.get("competitions", [])
            if not competitions:
                return None

            # Group bouts by start time to derive segments
            # ESPN provides exact segment times via bout-level date fields
            bout_times: set[str] = set()
            for comp in competitions:
                if "date" in comp:
                    bout_times.add(comp["date"])

            if not bout_times:
                return None

            # Sort times chronologically to determine segments
            sorted_times = sorted(bout_times)

            # Build segment_times dict based on number of distinct times
            segment_times: dict[str, Any] = {}
            time_to_segment: dict[str, str] = {}  # Map raw time strings to segment names

            if len(sorted_times) == 3:
                # PPV format: Early Prelims, Prelims, Main Card
                segment_times["early_prelims"] = self._parse_datetime(sorted_times[0])
                segment_times["prelims"] = self._parse_datetime(sorted_times[1])
                segment_times["main_card"] = self._parse_datetime(sorted_times[2])
                time_to_segment[sorted_times[0]] = "early_prelims"
                time_to_segment[sorted_times[1]] = "prelims"
                time_to_segment[sorted_times[2]] = "main_card"
            elif len(sorted_times) == 2:
                # Fight Night format: Prelims, Main Card
                segment_times["prelims"] = self._parse_datetime(sorted_times[0])
                segment_times["main_card"] = self._parse_datetime(sorted_times[1])
                time_to_segment[sorted_times[0]] = "prelims"
                time_to_segment[sorted_times[1]] = "main_card"
            else:
                # Single segment: Main Card only
                segment_times["main_card"] = self._parse_datetime(sorted_times[0])
                time_to_segment[sorted_times[0]] = "main_card"

            # Remove any None values (failed datetime parsing)
            segment_times = {k: v for k, v in segment_times.items() if v is not None}

            # Event start time is earliest segment
            start_time = min(segment_times.values()) if segment_times else None
            if not start_time:
                return None

            # Main card start for backwards compatibility
            main_card_start = segment_times.get("main_card")

            # Parse all bouts on the card
            # ESPN orders bouts chronologically, so we preserve that order
            bouts: list[Bout] = []
            for idx, comp in enumerate(competitions):
                bout_competitors = comp.get("competitors", [])
                if len(bout_competitors) < 2:
                    continue

                # Get fighter names
                f1_athlete = bout_competitors[0].get("athlete", {})
                f2_athlete = bout_competitors[1].get("athlete", {})
                f1_name = f1_athlete.get("displayName", "")
                f2_name = f2_athlete.get("displayName", "")

                if not f1_name or not f2_name:
                    continue

                # Determine segment from bout time
                bout_time = comp.get("date", "")
                segment = time_to_segment.get(bout_time, "main_card")

                bouts.append(
                    Bout(
                        fighter1=f1_name,
                        fighter2=f2_name,
                        segment=segment,
                        order=idx,
                    )
                )

            # Find the main event (last bout = headline fight)
            main_event = competitions[-1]

            # Extract fighters as "teams"
            competitors = main_event.get("competitors", [])
            if len(competitors) < 2:
                return None

            fighter1 = self._parse_fighter_as_team(competitors[0])
            fighter2 = self._parse_fighter_as_team(competitors[1])

            # Parse status from main event
            status = self._parse_ufc_status(main_event.get("status", {}))

            # Parse fight result data (only populated for finished fights)
            fight_result_method, finish_round, finish_time = self._parse_fight_result(main_event)
            fighter1_scores, fighter2_scores = self._parse_judge_scores(main_event)
            weight_class = self._parse_weight_class(main_event)

            logger.debug(
                "[ESPN_UFC] Event %s segments: %s, bouts: %d, result: %s",
                event_id,
                {k: v.isoformat() for k, v in segment_times.items()},
                len(bouts),
                fight_result_method,
            )

            return Event(
                id=event_id,
                provider=self.name,
                name=data.get("name", ""),
                short_name=f"{fighter1.short_name} vs {fighter2.short_name}",
                start_time=start_time,
                home_team=fighter1,
                away_team=fighter2,
                status=status,
                league="ufc",
                sport="mma",  # Lowercase code; display name from sports table
                main_card_start=main_card_start,
                segment_times=segment_times,
                bouts=bouts,
                fight_result_method=fight_result_method,
                finish_round=finish_round,
                finish_time=finish_time,
                weight_class=weight_class,
                fighter1_scores=fighter1_scores,
                fighter2_scores=fighter2_scores,
            )
        except Exception as e:
            logger.warning("[ESPN_UFC] Failed to parse event %s: %s", data.get("id", "unknown"), e)
            return None

    def _parse_fighter_as_team(self, competitor: dict) -> Team:
        """Convert UFC fighter to Team dataclass for compatibility."""
        athlete = competitor.get("athlete", {})

        # Get headshot URL
        headshots = athlete.get("headshots", {})
        logo_url = None
        if headshots:
            # Prefer full size, fallback to any available
            logo_url = headshots.get("full", {}).get("href")
            if not logo_url:
                for size in ["xlarge", "large", "medium"]:
                    if size in headshots:
                        logo_url = headshots[size].get("href")
                        break

        display_name = athlete.get("displayName", "")
        short_name = athlete.get("shortName", "")

        # For fighters, use last name as abbreviation (e.g., "Allen", "Silva")
        # This works better with templates like "{away_team_abbrev} @ {home_team_abbrev}"
        last_name = display_name.split()[-1] if display_name else short_name

        # Extract fighter record from records array (e.g., "8-1-0")
        record_summary = None
        for record in competitor.get("records", []):
            if record.get("type") == "total" or record.get("name") == "overall":
                record_summary = record.get("summary")
                break

        return Team(
            id=str(athlete.get("id", "")),
            provider=self.name,
            name=display_name,
            short_name=short_name,
            abbreviation=last_name,
            league="ufc",
            sport="mma",  # Lowercase code; display name from sports table
            logo_url=logo_url,
            color=None,
            record_summary=record_summary,
        )

    def _parse_ufc_status(self, status_data: dict) -> EventStatus:
        """Parse UFC event status."""
        state_map = {
            "pre": "scheduled",
            "in": "live",
            "post": "final",
        }
        # State is nested inside type object
        status_type = status_data.get("type", {})
        state = status_type.get("state", "pre")
        mapped_state = state_map.get(state, "scheduled")

        # Extract round (period) and time for finished fights
        period = status_data.get("period")
        clock = status_data.get("displayClock")

        return EventStatus(
            state=mapped_state,
            detail=status_type.get("detail"),
            period=period,
            clock=clock,
        )

    def _parse_fight_result(self, competition: dict) -> tuple[str | None, int | None, str | None]:
        """Parse fight result method, round, and time from competition data.

        Returns:
            Tuple of (result_method, finish_round, finish_time)
            result_method: 'ko', 'tko', 'submission', 'decision_unanimous',
                          'decision_split', 'decision_majority', or None
        """
        status = competition.get("status", {})
        details = competition.get("details", [])

        # Only parse results for finished fights
        if status.get("type", {}).get("state") != "post":
            return None, None, None

        # Get round and time from status
        finish_round = status.get("period")
        finish_time = status.get("displayClock")

        # Parse result method from details array
        result_method = None
        for detail in details:
            detail_text = detail.get("type", {}).get("text", "").lower()

            if "winner" in detail_text:
                if "decision" in detail_text:
                    # Check linescores to determine decision type
                    result_method = self._determine_decision_type(competition)
                elif "kotko" in detail_text or "ko" in detail_text:
                    # Distinguish KO vs TKO based on time/round
                    # Generally if fight ends very quickly in R1, more likely KO
                    # But ESPN doesn't distinguish clearly, so default to TKO
                    result_method = "tko"
                elif "submission" in detail_text or "sub" in detail_text:
                    result_method = "submission"
                break

        return result_method, finish_round, finish_time

    def _determine_decision_type(self, competition: dict) -> str:
        """Determine if decision was unanimous, split, or majority from judge scores.

        Note: ESPN API doesn't clearly expose split/majority distinction,
        so we default to unanimous for now.
        """
        # ESPN doesn't clearly expose split/majority distinction in the API
        # Future: could potentially infer from judge scorecards if available
        return "decision_unanimous"

    def _parse_judge_scores(self, competition: dict) -> tuple[list[int] | None, list[int] | None]:
        """Extract judge scores from competition linescores.

        Returns:
            Tuple of (fighter1_scores, fighter2_scores) where each is a list
            of total scores from each judge, or None if not available.
        """
        competitors = competition.get("competitors", [])
        if len(competitors) < 2:
            return None, None

        fighter1_scores = None
        fighter2_scores = None

        for comp in competitors:
            linescores = comp.get("linescores", [])
            if not linescores:
                continue

            # The top-level linescore has total, nested ones are per-round
            top_linescore = linescores[0]
            nested = top_linescore.get("linescores", [])

            if nested:
                # Each nested entry is a round score from judges
                # Sum them to get total per judge (or use total value)
                total_value = top_linescore.get("value")
                if total_value is not None:
                    # ESPN provides total as single value, but we want per-judge
                    # The nested linescores are round-by-round, not per-judge
                    # So we'll store the total as a single-element list
                    scores = [int(total_value)]
                    if comp.get("order") == 1 or comp.get("order") == 2:
                        order = comp.get("order")
                        if order == 1:
                            fighter1_scores = scores
                        else:
                            fighter2_scores = scores

        return fighter1_scores, fighter2_scores

    def _parse_weight_class(self, competition: dict) -> str | None:
        """Extract weight class from competition type."""
        comp_type = competition.get("type", {})
        return comp_type.get("abbreviation")
