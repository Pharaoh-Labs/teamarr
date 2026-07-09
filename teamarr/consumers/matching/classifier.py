"""Stream classification for matching strategy selection.

Classifies streams into categories that determine which matching
strategy to use:
- TEAM_VS_TEAM: Standard team sports (NFL, NBA, Soccer, etc.)
- EVENT_CARD: Combat sports with event cards (UFC, Boxing)
- PLACEHOLDER: Filler streams with no event info (skip)
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, time
from enum import Enum
from re import Pattern
from typing import cast

from teamarr.consumers.matching.normalizer import NormalizedStream, normalize_stream
from teamarr.services.detection_keywords import DetectionKeywordService

logger = logging.getLogger(__name__)


class StreamCategory(Enum):
    """Stream category for matching strategy selection."""

    TEAM_VS_TEAM = "team_vs_team"  # Standard team matchup (vs/@/at)
    EVENT_CARD = "event_card"  # Combat sports (UFC, Boxing)
    RACING_EVENT = "racing_event"  # Racing race weekends (F1, NASCAR, etc.)
    TENNIS_MATCH = "tennis_match"  # Tennis matches ("Wimbledon: Zheng vs Norrie")
    TEAM_ONLY = "team_only"  # Single-team branded stream (e.g., "NHL | Toronto Maple Leafs")
    PLACEHOLDER = "placeholder"  # No event info, skip


@dataclass
class ClassifiedStream:
    """Result of stream classification with extracted components."""

    category: StreamCategory
    normalized: NormalizedStream

    # For TEAM_VS_TEAM: extracted team names
    # For EVENT_CARD: also used for fighter names (fighters treated as "teams")
    team1: str | None = None
    team2: str | None = None
    separator_found: str | None = None

    # For EVENT_CARD: event hint (e.g., "UFC 315")
    event_hint: str | None = None

    # For EVENT_CARD: card segment (e.g., "early_prelims", "prelims", "main_card")
    card_segment: str | None = None

    # Detected league hint (for any category)
    # Can be a single league code or list for umbrella brands (e.g., EFL → [eng.2, eng.3, eng.4])
    league_hint: str | list[str] | None = None

    # Detected sport hint (e.g., "Hockey", "Football")
    # Can be a list for ambiguous terms (e.g., ["Soccer", "Football"])
    sport_hint: str | list[str] | None = None

    # Track if custom regex was used
    custom_regex_used: bool = False

    # Feed hint: "home" or "away" if a feed indicator was detected in stream name
    # Used by feed separation to resolve to actual team after event matching
    feed_hint: str | None = None


@dataclass
class CustomRegexConfig:
    """Configuration for custom regex extraction patterns."""

    # TEAM_VS_TEAM patterns
    teams_pattern: str | None = None
    teams_enabled: bool = False
    date_pattern: str | None = None
    date_enabled: bool = False
    month_pattern: str | None = None
    month_enabled: bool = False
    day_pattern: str | None = None
    day_enabled: bool = False
    time_pattern: str | None = None
    time_enabled: bool = False
    league_pattern: str | None = None
    league_enabled: bool = False

    # EVENT_CARD patterns (UFC, Boxing, MMA)
    fighters_pattern: str | None = None
    fighters_enabled: bool = False
    event_name_pattern: str | None = None
    event_name_enabled: bool = False

    # Compiled patterns (cached)
    _compiled_teams: Pattern | None = None
    _compiled_date: Pattern | None = None
    _compiled_month: Pattern | None = None
    _compiled_day: Pattern | None = None
    _compiled_time: Pattern | None = None
    _compiled_league: Pattern | None = None
    _compiled_fighters: Pattern | None = None
    _compiled_event_name: Pattern | None = None

    def get_pattern(self) -> Pattern | None:
        """Get compiled teams regex pattern, compiling on first access."""
        if not self.teams_enabled or not self.teams_pattern:
            return None

        if self._compiled_teams is None:
            try:
                self._compiled_teams = re.compile(self.teams_pattern, re.IGNORECASE)
            except re.error as e:
                logger.warning("[CLASSIFY] Invalid custom teams regex pattern: %s", e)
                return None

        return self._compiled_teams

    def get_date_pattern(self) -> Pattern | None:
        """Get compiled date regex pattern, compiling on first access."""
        if not self.date_enabled or not self.date_pattern:
            return None

        if self._compiled_date is None:
            try:
                self._compiled_date = re.compile(self.date_pattern, re.IGNORECASE)
            except re.error as e:
                logger.warning("[CLASSIFY] Invalid custom date regex pattern: %s", e)
                return None

        return self._compiled_date

    def get_month_pattern(self) -> Pattern | None:
        """Get compiled month regex pattern, compiling on first access."""
        if not self.month_enabled or not self.month_pattern:
            return None

        if self._compiled_month is None:
            try:
                self._compiled_month = re.compile(self.month_pattern, re.IGNORECASE)
            except re.error as e:
                logger.warning("[CLASSIFY] Invalid custom month regex pattern: %s", e)
                return None

        return self._compiled_month

    def get_day_pattern(self) -> Pattern | None:
        """Get compiled day regex pattern, compiling on first access."""
        if not self.day_enabled or not self.day_pattern:
            return None

        if self._compiled_day is None:
            try:
                self._compiled_day = re.compile(self.day_pattern, re.IGNORECASE)
            except re.error as e:
                logger.warning("[CLASSIFY] Invalid custom day regex pattern: %s", e)
                return None

        return self._compiled_day

    def get_time_pattern(self) -> Pattern | None:
        """Get compiled time regex pattern, compiling on first access."""
        if not self.time_enabled or not self.time_pattern:
            return None

        if self._compiled_time is None:
            try:
                self._compiled_time = re.compile(self.time_pattern, re.IGNORECASE)
            except re.error as e:
                logger.warning("[CLASSIFY] Invalid custom time regex pattern: %s", e)
                return None

        return self._compiled_time

    def get_league_pattern(self) -> Pattern | None:
        """Get compiled league regex pattern, compiling on first access."""
        if not self.league_enabled or not self.league_pattern:
            return None

        if self._compiled_league is None:
            try:
                self._compiled_league = re.compile(self.league_pattern, re.IGNORECASE)
            except re.error as e:
                logger.warning("[CLASSIFY] Invalid custom league regex pattern: %s", e)
                return None

        return self._compiled_league

    def get_fighters_pattern(self) -> Pattern | None:
        """Get compiled fighters regex pattern for EVENT_CARD streams."""
        if not self.fighters_enabled or not self.fighters_pattern:
            return None

        if self._compiled_fighters is None:
            try:
                self._compiled_fighters = re.compile(self.fighters_pattern, re.IGNORECASE)
            except re.error as e:
                logger.warning("[CLASSIFY] Invalid custom fighters regex pattern: %s", e)
                return None

        return self._compiled_fighters

    def get_event_name_pattern(self) -> Pattern | None:
        """Get compiled event name regex pattern for EVENT_CARD streams."""
        if not self.event_name_enabled or not self.event_name_pattern:
            return None

        if self._compiled_event_name is None:
            try:
                self._compiled_event_name = re.compile(self.event_name_pattern, re.IGNORECASE)
            except re.error as e:
                logger.warning("[CLASSIFY] Invalid custom event_name regex pattern: %s", e)
                return None

        return self._compiled_event_name


def extract_teams_with_custom_regex(
    text: str,
    config: CustomRegexConfig,
) -> tuple[str | None, str | None, bool]:
    """Extract team names using custom regex pattern.

    Args:
        text: Stream name (normalized)
        config: Custom regex configuration

    Returns:
        Tuple of (team1, team2, success)
    """
    pattern = config.get_pattern()
    if not pattern:
        return None, None, False

    match = pattern.search(text)
    if not match:
        return None, None, False

    # Try numbered groups first (group 1 and 2)
    groups = match.groups()
    if len(groups) >= 2:
        team1 = groups[0].strip() if groups[0] else None
        team2 = groups[1].strip() if groups[1] else None
        if team1 and team2:
            return team1, team2, True

    # Try named groups (?P<team1>...) and (?P<team2>...)
    try:
        team1 = match.group("team1")
        team2 = match.group("team2")
        if team1 and team2:
            return team1.strip(), team2.strip(), True
    except (IndexError, re.error):
        pass

    return None, None, False


def extract_fighters_with_custom_regex(
    text: str,
    config: CustomRegexConfig,
) -> tuple[str | None, str | None, bool]:
    """Extract fighter names using custom regex pattern for EVENT_CARD streams.

    Args:
        text: Stream name (normalized)
        config: Custom regex configuration

    Returns:
        Tuple of (fighter1, fighter2, success)
    """
    pattern = config.get_fighters_pattern()
    if not pattern:
        return None, None, False

    match = pattern.search(text)
    if not match:
        return None, None, False

    # Try numbered groups first (group 1 and 2)
    groups = match.groups()
    if len(groups) >= 2:
        fighter1 = groups[0].strip() if groups[0] else None
        fighter2 = groups[1].strip() if groups[1] else None
        if fighter1 and fighter2:
            return fighter1, fighter2, True

    # Try named groups (?P<fighter1>...) and (?P<fighter2>...)
    try:
        fighter1 = match.group("fighter1")
        fighter2 = match.group("fighter2")
        if fighter1 and fighter2:
            return fighter1.strip(), fighter2.strip(), True
    except (IndexError, re.error):
        pass

    return None, None, False


def extract_event_name_with_custom_regex(
    text: str,
    config: CustomRegexConfig,
) -> str | None:
    """Extract event name using custom regex pattern for EVENT_CARD streams.

    Args:
        text: Stream name (original, not normalized)
        config: Custom regex configuration

    Returns:
        Event name string or None
    """
    pattern = config.get_event_name_pattern()
    if not pattern:
        return None

    match = pattern.search(text)
    if not match:
        return None

    # Try named group (?P<event_name>...)
    try:
        event_name = match.group("event_name")
        if event_name:
            return event_name.strip()
    except (IndexError, re.error):
        pass

    # Try first capture group
    groups = match.groups()
    if groups and groups[0]:
        return groups[0].strip()

    return None


def extract_date_with_custom_regex(
    text: str,
    config: CustomRegexConfig,
) -> date | None:
    """Extract date using custom regex pattern.

    Supports:
    - Named group: (?P<date>...) - returns raw string to parse
    - Named groups: (?P<month>...) (?P<day>...) (?P<year>...) - combines
    - Single capture group - returns raw string to parse
    - Separate month/day patterns - each extracts independently, then combines

    Args:
        text: Stream name (original, not normalized)
        config: Custom regex configuration

    Returns:
        Extracted date or None
    """
    from datetime import datetime

    # Strategy 1: Single date pattern (full date or month+day named groups within it)
    pattern = config.get_date_pattern()
    if pattern:
        match = pattern.search(text)
        if match:
            try:
                # Try named group 'date' first (full date string)
                try:
                    date_str = match.group("date")
                    if date_str:
                        return _parse_date_string(date_str.strip())
                except (IndexError, re.error):
                    pass

                # Try individual named groups (month, day, year)
                try:
                    month_str = match.group("month")
                    day_str = match.group("day")
                    if month_str and day_str:
                        month = _parse_month(month_str.strip())
                        day = int(day_str.strip())
                        try:
                            year = int(match.group("year").strip())
                            if year < 100:
                                year += 2000 if year < 50 else 1900
                        except (IndexError, re.error, ValueError, AttributeError):
                            year = datetime.now().year
                        return date(year, month, day)
                except (IndexError, re.error, ValueError, AttributeError):
                    pass

                # Try first capture group as raw date string
                groups = match.groups()
                if groups and groups[0]:
                    return _parse_date_string(groups[0].strip())

            except (ValueError, TypeError) as e:
                logger.debug("[CLASSIFY] Failed to parse custom date: %s", e)

    # Strategy 2: Separate month + day patterns
    month_pattern = config.get_month_pattern()
    day_pattern = config.get_day_pattern()
    if month_pattern and day_pattern:
        month_match = month_pattern.search(text)
        day_match = day_pattern.search(text)
        if month_match and day_match:
            try:
                # Extract month: try named group, then first capture group
                month_str = None
                try:
                    month_str = month_match.group("month")
                except (IndexError, re.error):
                    pass
                if not month_str and month_match.groups():
                    month_str = month_match.groups()[0]
                if not month_str:
                    month_str = month_match.group(0)

                # Extract day: try named group, then first capture group
                day_str = None
                try:
                    day_str = day_match.group("day")
                except (IndexError, re.error):
                    pass
                if not day_str and day_match.groups():
                    day_str = day_match.groups()[0]
                if not day_str:
                    day_str = day_match.group(0)

                if month_str and day_str:
                    month = _parse_month(month_str.strip())
                    day = int(day_str.strip())
                    year = datetime.now().year
                    return date(year, month, day)
            except (ValueError, TypeError, AttributeError) as e:
                logger.debug("[CLASSIFY] Failed to parse separate month/day: %s", e)

    return None


def _parse_month(month_str: str) -> int:
    """Parse month from string (name or number)."""
    month_names = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    month_lower = month_str.lower()
    if month_lower in month_names:
        return month_names[month_lower]
    return int(month_str)


def _parse_date_string(date_str: str) -> date | None:
    """Parse various date string formats."""
    from datetime import datetime

    # Common formats to try
    formats = [
        "%d %b",  # 14 Jan
        "%d %B",  # 14 January
        "%b %d",  # Jan 14
        "%B %d",  # January 14
        "%m/%d/%Y",  # 01/14/2026
        "%m/%d/%y",  # 01/14/26
        "%d/%m/%Y",  # 14/01/2026
        "%d/%m/%y",  # 14/01/26
        "%Y-%m-%d",  # 2026-01-14
        "%d-%m-%Y",  # 14-01-2026
    ]

    # Clean up ordinal suffixes (1st, 2nd, 3rd, 4th)
    date_str = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", date_str, flags=re.IGNORECASE)

    for fmt in formats:
        try:
            parsed = datetime.strptime(date_str, fmt)
            # If no year in format, use current year
            if "%Y" not in fmt and "%y" not in fmt:
                parsed = parsed.replace(year=datetime.now().year)
            return parsed.date()
        except ValueError:
            continue

    return None


def extract_time_with_custom_regex(
    text: str,
    config: CustomRegexConfig,
) -> time | None:
    """Extract time using custom regex pattern.

    Supports:
    - Named group: (?P<time>...) - returns raw string to parse
    - Named groups: (?P<hour>...) (?P<minute>...) (?P<ampm>...) - combines
    - Single capture group - returns raw string to parse

    Args:
        text: Stream name (original, not normalized)
        config: Custom regex configuration

    Returns:
        Extracted time or None
    """
    pattern = config.get_time_pattern()
    if not pattern:
        return None

    match = pattern.search(text)
    if not match:
        return None

    try:
        # Try named group 'time' first (full time string)
        try:
            time_str = match.group("time")
            if time_str:
                return _parse_time_string(time_str.strip())
        except (IndexError, re.error):
            pass

        # Try individual named groups (hour, minute, ampm)
        try:
            hour = int(match.group("hour").strip())
            try:
                minute = int(match.group("minute").strip())
            except (IndexError, re.error, ValueError, AttributeError):
                minute = 0

            try:
                ampm = match.group("ampm").strip().upper()
                if ampm == "PM" and hour < 12:
                    hour += 12
                elif ampm == "AM" and hour == 12:
                    hour = 0
            except (IndexError, re.error, ValueError, AttributeError):
                pass

            return time(hour, minute)
        except (IndexError, re.error, ValueError, AttributeError):
            pass

        # Try first capture group as raw time string
        groups = match.groups()
        if groups and groups[0]:
            return _parse_time_string(groups[0].strip())

    except (ValueError, TypeError) as e:
        logger.debug("[CLASSIFY] Failed to parse custom time: %s", e)

    return None


def _parse_time_string(time_str: str) -> time | None:
    """Parse various time string formats."""
    from datetime import datetime

    # Common formats to try
    formats = [
        "%I:%M%p",  # 6:45pm
        "%I:%M %p",  # 6:45 pm
        "%I%p",  # 6pm
        "%I %p",  # 6 pm
        "%H:%M",  # 18:45
        "%H%M",  # 1845
    ]

    # Normalize: remove spaces between number and am/pm
    time_str_normalized = re.sub(r"(\d+)\s*(am|pm)", r"\1\2", time_str, flags=re.IGNORECASE)

    for fmt in formats:
        try:
            parsed = datetime.strptime(time_str_normalized, fmt)
            return parsed.time()
        except ValueError:
            continue

    # Also try the original string
    if time_str != time_str_normalized:
        for fmt in formats:
            try:
                parsed = datetime.strptime(time_str, fmt)
                return parsed.time()
            except ValueError:
                continue

    return None


def extract_league_with_custom_regex(
    text: str,
    config: CustomRegexConfig,
) -> str | None:
    """Extract league hint using custom regex pattern.

    Supports:
    - Named group: (?P<league>...) - returns the captured league code
    - Single capture group - returns the captured string

    Args:
        text: Stream name (original, not normalized)
        config: Custom regex configuration

    Returns:
        Extracted league code or None
    """
    pattern = config.get_league_pattern()
    if not pattern:
        return None

    match = pattern.search(text)
    if not match:
        return None

    try:
        # Try named group 'league' first
        try:
            league = match.group("league")
            if league:
                return league.strip().lower()
        except (IndexError, re.error):
            pass

        # Try first capture group
        groups = match.groups()
        if groups and groups[0]:
            return groups[0].strip().lower()

    except (ValueError, TypeError) as e:
        logger.debug("[CLASSIFY] Failed to extract custom league: %s", e)

    return None


# =============================================================================
# PLACEHOLDER DETECTION
# =============================================================================


def is_placeholder(text: str) -> bool:
    """Check if stream name matches placeholder patterns.

    Placeholders are filler streams with no real event info,
    like "ESPN+ 45" or "Coming Soon".

    Args:
        text: Normalized stream name

    Returns:
        True if stream is a placeholder
    """
    if not text:
        return True

    text_lower = text.lower().strip()

    # Check against placeholder patterns via service
    if DetectionKeywordService.is_placeholder(text_lower):
        return True

    # Additional check: very short names with just numbers
    if re.match(r"^[\d\s\-:]+$", text_lower):
        return True

    return False


# =============================================================================
# GAME SEPARATOR DETECTION
# =============================================================================


def find_game_separator(text: str) -> tuple[str | None, int]:
    """Find game separator in stream name.

    Args:
        text: Stream name (should be normalized)

    Returns:
        Tuple of (separator found, position) or (None, -1)
    """
    if not text:
        return None, -1

    return DetectionKeywordService.find_separator(text)


def extract_teams_from_separator(
    text: str, separator: str, sep_position: int
) -> tuple[str | None, str | None]:
    """Extract team names from a stream with a separator.

    Args:
        text: Stream name
        separator: The separator found (e.g., " vs ")
        sep_position: Position of separator in text

    Returns:
        Tuple of (team1, team2)
    """
    if sep_position < 0:
        return None, None

    team1 = text[:sep_position].strip()
    team2 = text[sep_position + len(separator) :].strip()

    # Clean up teams (remove DATE_MASK, TIME_MASK, trailing punctuation)
    team1 = _clean_team_name(team1)
    team2 = _clean_team_name(team2)

    # Validate: both teams should have substance
    # Minimum 3 chars - even short team abbrevs are 3+ (USC, LSU, BYU, etc.)
    if not team1 or len(team1) < 3:
        team1 = None
    if not team2 or len(team2) < 3:
        team2 = None

    return team1, team2


def _clean_team_name(name: str) -> str:
    """Clean extracted team name."""
    if not name:
        return ""

    # Normalize newlines and carriage returns to spaces
    # Some streams have literal newlines: "NFL\n01: Bills vs Broncos"
    name = re.sub(r"[\r\n]+", " ", name)

    # Truncate at "//" which is often used as timezone separator
    # "Indiana Pacers // UK Wed 14 Jan" → "Indiana Pacers"
    if " // " in name:
        name = name.split(" // ")[0]

    # Remove datetime masks
    name = re.sub(r"\bDATE_MASK\b", "", name)
    name = re.sub(r"\bTIME_MASK\b", "", name)

    # Remove parentheses left empty/near-empty after datetime mask removal
    # Handles: () (   ) (:05) (  -- ) (  --  :40) etc.
    name = re.sub(r"\(\s*[\s:\-]*\d{0,2}\s*\)", "", name)

    # Clean up "@ ET", "@ EST", "@ PT", etc. at end
    name = re.sub(r"\s*@\s*[A-Z]{2,4}T?\s*$", "", name, flags=re.IGNORECASE)

    # Remove standalone timezone codes (ET, EST, PT, PST, CT, CST, MT, MST, etc.)
    # These can remain after date/time stripping: "Jan 17 5PM ET" → "ET"
    name = re.sub(
        r"^(E|P|C|M)(S|D)?T$",  # ET, EST, EDT, PT, PST, PDT, CT, CST, CDT, MT, MST, MDT
        "",
        name,
        flags=re.IGNORECASE,
    )

    # Remove trailing punctuation (NOT digits - they could be team names like 49ers, 76ers)
    name = re.sub(r"[\s\-:.,@]+$", "", name)

    # Remove channel numbers like "(1)" or "[2]"
    name = re.sub(r"\s*[\(\[]\d+[\)\]]\s*$", "", name)

    # Remove parenthetical gender markers: English (W)/(M)/(Women)/(Men) seen in
    # NCAAB streams ("LSU (W)", "Duke (M)") and Spanish/Portuguese (F)/(Femenino)/
    # (Masculino) seen in non-English feeds ("España (F)").
    name = re.sub(
        r"\s*\((?:W|M|F|Women|Men|Fem[ei]nin[oa]|Masculin[oa])\)",
        "",
        name,
        flags=re.IGNORECASE,
    )

    # Remove HD, SD, 4K, UHD quality indicators (at start or end)
    name = re.sub(r"^\s*\b(HD|SD|FHD|4K|UHD)\b\s*", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+\b(HD|SD|FHD|4K|UHD)\b\s*$", "", name, flags=re.IGNORECASE)

    # Remove broadcast network indicators like (CBS), (FOX), (ABC), (NBC), (ESPN)
    name = re.sub(
        r"\s*\((CBS|FOX|ABC|NBC|ESPN|ESPN2|TNT|TBS|FS1|FS2|NBCSN|USA|PEACOCK)\)\s*$",
        "",
        name,
        flags=re.IGNORECASE,
    )

    # Strip round/competition indicators at end of team names
    round_pattern = r"""
        \s*\(
        (?:
            (?:Round|Rd|Rnd|R)\s*\d+\w*  |  # Round 3, Rd 3, R3
            \d+(?:st|nd|rd|th)?\s*(?:Round|Rd|Leg)  |  # 3rd Round, 1st Leg
            (?:First|Second|Third|Fourth|Fifth)\s*(?:Round|Leg)  |  # Third Round
            (?:Group|Grp|Gr)\s*\w*  |  # Group A, Group Stage
            (?:Matchday|MD|Week|Wk)\s*\d*  |  # Matchday 5, MD5, Week 10
            (?:Leg|Game)\s*(?:One|Two|\d+)  |  # Leg 1, Leg One
            (?:Quarter|Semi|Half)?-?(?:Final|Finals)  |  # Final, Semi-Final
            (?:QF|SF|F)  |  # QF, SF, F
            (?:Play-?off|Play-?offs)  |  # Playoff, Play-off
            (?:Qualifying|Qual|Q)\d*  |  # Qualifying, Q1
            (?:Prelim|Preliminary)  |  # Preliminary
            (?:1H|2H|OT|ET)  |  # 1st half, overtime, extra time markers
            (?:Live|LIVE|Replay|Encore)  # Broadcast markers
        )
        \s*\)
    """
    name = re.sub(round_pattern, "", name, flags=re.IGNORECASE | re.VERBOSE)

    # Handle "|" separator - preserve pipe content for fuzzy matching disambiguation
    # The matcher will try both sides of the pipe and pick the one that matches.
    # Here we only strip OBVIOUS prefix noise (league hints, channel numbers) from the
    # start, keeping the rest intact for the matcher to disambiguate.
    # "NFL | Bills vs Broncos" → "Bills vs Broncos" (NFL is league hint)
    # "Montreal Canadiens | Bell Centre" → "Montreal Canadiens | Bell Centre" (pass through)
    if "|" in name:
        parts = name.split("|")
        first_part = parts[0].strip()
        rest = "|".join(parts[1:]).strip()

        # Check if first part is a known prefix (league hint) that should be stripped
        # Use existing detection - no hardcoded lists
        first_is_league = detect_league_hint(first_part + ":") is not None
        first_is_sport = detect_sport_hint(first_part) is not None

        # Check if first part is a provider/channel prefix pattern
        # Handles: "US (Paramount 010)", "UK (Sky Sports 042)", "CA (TSN 3)"
        first_is_provider = bool(re.match(r"^[A-Z]{2,3}\s*\(.*\d+\)$", first_part, re.IGNORECASE))

        # Also strip if first part is mostly datetime placeholders
        first_stripped = re.sub(r"\bDATE_MASK\b", "", first_part)
        first_stripped = re.sub(r"\bTIME_MASK\b", "", first_stripped)
        first_stripped = re.sub(r"\b[ECPM][SD]?T\b", "", first_stripped, flags=re.IGNORECASE)
        first_stripped = re.sub(r"[\s\-:.,]+", " ", first_stripped).strip()
        first_is_datetime_noise = len(first_stripped) < 3

        if first_is_league or first_is_sport or first_is_datetime_noise or first_is_provider:
            # First part is prefix noise - take the rest
            # Check for colon in rest (show name prefix pattern)
            if ":" in rest:
                after_colon = rest.split(":")[-1].strip()
                if after_colon and len(after_colon) >= 3:
                    name = after_colon
                else:
                    name = rest
            else:
                name = rest
        # else: keep the full pipe-separated string for matcher disambiguation

    # Strip channel number prefixes like "02 -", "15 -", "142 -" at the start
    name = re.sub(r"^\d+\s*-\s*", "", name)

    # Strip leading channel numbers like "02 :", "15 :", "142 :"
    name = re.sub(r"^\d+\s*:\s*", "", name)

    # Strip 1-2 digit channel numbers followed by whitespace only (no dash/colon)
    # "01 Bills" → "Bills", "03 49ers" → "49ers"
    # Safe because after separator split, a leading 1-2 digit number + space is a channel number
    name = re.sub(r"^\d{1,2}\s+", "", name)

    # Strip numbered channel prefixes like "NFL Game Pass 03:", "ESPN+ 45:"
    name = re.sub(r"^[A-Za-z][A-Za-z\s+]*\d*:\s*", "", name)

    # Strip show name prefixes like "MNF Playbook:", "NFL RedZone:"
    prev = None
    while prev != name:
        prev = name
        name = re.sub(r"^[A-Z][A-Za-z\s]+:\s*", "", name)

    # Strip common league abbreviations at start (even without colon)
    # "NFL Bills" → "Bills", "NBA 03 Lakers" → "03 Lakers"
    # This handles streams without pipe separators like "NFL 03 3PM Texans at Patriots"
    name = re.sub(
        r"^(NFL|NBA|MLB|NHL|MLS|NCAAF|NCAAB|NCAAW|WNBA|EPL|UCL|UFC|MMA)\s+",
        "",
        name,
        flags=re.IGNORECASE,
    )

    # Re-strip channel numbers in case league prefix revealed one
    # "NFL 03 Bills" → after league strip: "03 Bills" → "Bills"
    name = re.sub(r"^\d{1,2}\s+", "", name)

    # Remove leading punctuation and whitespace
    name = re.sub(r"^[\s\-:.,]+", "", name)

    # NOW remove unmasked time patterns at the start (e.g., "3PM Texans" → "Texans")
    # This must happen AFTER prefix stripping so the time is actually at the start
    name = re.sub(r"^\s*\d{1,2}(?::\d{2})?\s*(?:AM|PM)\s*", "", name, flags=re.IGNORECASE)

    # Final cleanup of leading/trailing whitespace
    return name.strip()


# =============================================================================
# LEAGUE HINT DETECTION
# =============================================================================


def detect_league_hint(text: str) -> str | list[str] | None:
    """Detect league from stream name patterns.

    Examples:
        "NHL: Bruins vs Rangers" → "nhl"
        "EPL - Arsenal vs Chelsea" → "eng.1"
        "UFC 315: Main Card" → "ufc"
        "EFL: Portsmouth vs Southampton" → ["eng.2", "eng.3", "eng.4"]

    Args:
        text: Stream name (should be normalized)

    Returns:
        League code (str), list of league codes (for umbrella brands), or None
    """
    if not text:
        return None

    return DetectionKeywordService.detect_league(text)


# Gender keywords that indicate women's leagues. English (W)/Women plus
# Spanish/Portuguese femenino/femenina/feminino/feminina and the (F) marker.
# fem[ei]nin[oa] requires the trailing o/a so English "feminine" never matches.
_WOMENS_KEYWORDS = re.compile(r"\(W\)|\(F\)|\bWomen|\bfem[ei]nin[oa]\b", re.IGNORECASE)
# Gender keywords that indicate men's leagues. English (M)/Men plus
# Spanish/Portuguese masculino/masculina ((M) already doubles as Masculino).
_MENS_KEYWORDS = re.compile(r"\(M\)|\bMen(?:'s|s)?\b|\bmasculin[oa]\b", re.IGNORECASE)
# Regex to identify gendered league codes
_WOMENS_LEAGUE_RE = re.compile(r"\bwomens?\b", re.IGNORECASE)
_MENS_LEAGUE_RE = re.compile(r"\bmens?\b", re.IGNORECASE)


def _narrow_by_gender(
    leagues: list[str], stream_name: str
) -> str | list[str]:
    """Narrow an umbrella league hint using gender markers in the stream name.

    If the stream contains a women's marker ((W), Women, (F), femenino/femenina),
    keep only women's leagues. If a men's marker ((M), Men, masculino/masculina),
    keep only men's leagues. If neither, return the full list.

    Examples:
        ["mens-college-basketball", "womens-college-basketball"] + "(W)"
            → "womens-college-basketball"
        ["mens-college-basketball", "womens-college-basketball"] + "(M)"
            → "mens-college-basketball"
        ["eng.2", "eng.3", "eng.4"] + "(W)"
            → ["eng.2", "eng.3", "eng.4"]  (no gendered pair)
    """
    has_womens = _WOMENS_KEYWORDS.search(stream_name)
    has_mens = _MENS_KEYWORDS.search(stream_name) if not has_womens else None

    if not has_womens and not has_mens:
        return leagues

    # Check if any league in the list has gendered counterparts
    if has_womens:
        womens = [lg for lg in leagues if _WOMENS_LEAGUE_RE.search(lg)]
        if womens:
            return womens[0] if len(womens) == 1 else womens
    elif has_mens:
        mens = [lg for lg in leagues if _MENS_LEAGUE_RE.search(lg)]
        if mens:
            return mens[0] if len(mens) == 1 else mens

    return leagues


def detect_sport_hint(text: str) -> str | None:
    """Detect sport type from stream name.

    Unlike league hints which only match at start of string,
    sport hints can match anywhere (e.g., "Ice Hockey" in the middle).

    Examples:
        "US (BTN+) | Ice Hockey (W): Minnesota at Wisconsin" → "Hockey"
        "ESPN: NFL Sunday Football" → "Football"
        "Basketball: Lakers vs Celtics" → "Basketball"

    Args:
        text: Stream name (should be normalized)

    Returns:
        Sport name matching leagues.sport column if detected, None otherwise
    """
    if not text:
        return None

    return cast("str | None", DetectionKeywordService.detect_sport(text))


# =============================================================================
# EVENT CARD DETECTION
# =============================================================================


def is_event_card(text: str, league_event_type: str | None = None) -> bool:
    """Check if stream is a combat sports event card (UFC, MMA, Boxing).

    Uses detect_event_type() which checks event_type_keywords.

    Args:
        text: Normalized stream name
        league_event_type: Optional event_type from leagues table

    Returns:
        True if stream is a combat sports event card
    """
    if not text:
        return False

    # If we know the league type, use that
    if league_event_type == "event_card":
        return True

    # Use event type detection - checks EVENT_CARD keywords
    detected = DetectionKeywordService.detect_event_type(text)
    return detected == "EVENT_CARD"


# Known racing league codes — a hardcoded mirror of the sport='racing' leagues
# in schema.sql (this module is pure text classification, no DB access).
# Kept in sync by test_racing_league_hints_cover_all_schema_racing_leagues.
# Used as a secondary trigger so streams in mixed-sport groups (where
# team_vs_team dominates the league_event_type vote) still reach the
# RACING_EVENT path when detect_league_hint() already identified them as
# motorsports.
_RACING_LEAGUE_HINTS: frozenset[str] = frozenset(
    {"f1", "nascar-cup", "nascar-xfinity", "nascar-truck", "indycar", "motogp", "imsa", "wec"}
)


def is_racing(
    league_event_type: str | None = None,
    league_hint: str | list[str] | None = None,
    sport_hint: str | list[str] | None = None,
    event_league_sport: str | None = None,
) -> bool:
    """Check if a stream's league is a racing/motorsports league.

    Three independent triggers (mirrors is_event_card() pattern):
    1. league_event_type == "event" — dominant league type gate. The "event"
       type is shared by all tournament sports (racing, tennis, golf), so
       when the caller knows the dominant SPORT of the group's event-type
       leagues (event_league_sport), a non-racing sport disables this
       trigger — a tennis-only group must not classify streams as racing.
       None preserves legacy behavior (racing owns "event").
    2. league_hint is a known racing league code — league keyword fallback
    3. sport_hint == "Racing" — sport keyword fallback

    Triggers 2 and 3 let streams in mixed-sport groups (where team_vs_team
    dominates) still reach the RACING_EVENT path when text-based detection
    already identifies them as motorsports.

    Args:
        league_event_type: event_type from leagues table (e.g., "event" for racing)
        league_hint: Detected league hint from stream text
        sport_hint: Detected sport hint from stream text
        event_league_sport: Dominant sport of the group's event-type leagues

    Returns:
        True if the league is configured as an "event" (racing) league
    """
    if league_event_type == "event" and event_league_sport in (None, "racing"):
        return True
    if isinstance(league_hint, str) and league_hint in _RACING_LEAGUE_HINTS:
        return True
    if isinstance(sport_hint, str) and sport_hint.lower() == "racing":
        return True
    return False


# Motorsports series names — text evidence that a string is actually about
# racing. Used by the EPG racing fallback, which re-classifies arbitrary
# programme titles with league_event_type="event": racing is the classifier's
# default bucket there, so without this gate any documentary or movie title
# reaches the racing matcher and can bind to "the race happening today" by
# date coverage ("Brimstone" fuzzy-matched Silverstone at 62). Series names
# only — venue words like "Silverstone" are places, not proof of a broadcast.
# Deliberately NOT in SPORT_HINT_PATTERNS: a global Racing sport hint would
# make is_racing trigger 3 fire during primary classification and reroute
# team-group streams (see test_racing_only_applies_for_event_league_type).
RACING_TEXT_EVIDENCE: Pattern[str] = re.compile(
    r"\b(?:"
    r"formula\s*[123e]|f1|nascar|indycar|indy\s*(?:500|nxt)|"
    r"motogp|moto\s*[23]|grand\s+prix|imsa|supercross|motocross"
    r")\b",
    re.IGNORECASE,
)


def has_racing_text_evidence(text: str) -> bool:
    """True when the text names a motorsports series (or 'grand prix')."""
    return bool(text) and RACING_TEXT_EVIDENCE.search(text) is not None


# Known tennis league codes — mirror of the sport='tennis' leagues in
# schema.sql (this module is pure text classification, no DB access).
_TENNIS_LEAGUE_HINTS: frozenset[str] = frozenset({"atp", "wta"})


def is_tennis(
    league_event_type: str | None = None,
    league_hint: str | list[str] | None = None,
    sport_hint: str | list[str] | None = None,
    event_league_sport: str | None = None,
) -> bool:
    """Check if a stream belongs to a tennis league.

    Mirrors is_racing()'s trigger structure:
    1. league_event_type == "event" AND the group's event-type leagues are
       tennis — the tennis-group gate (requires the caller to resolve
       event_league_sport; "event" alone is ambiguous with racing/golf)
    2. league_hint is a known tennis league code (atp/wta)
    3. sport_hint == "Tennis" — sport keyword fallback (real streams often
       carry a literal "Tennis" token, e.g. "... :Tennis 13")
    """
    if league_event_type == "event" and event_league_sport == "tennis":
        return True
    if isinstance(league_hint, str) and league_hint in _TENNIS_LEAGUE_HINTS:
        return True
    if isinstance(sport_hint, str) and sport_hint.lower() == "tennis":
        return True
    return False


def extract_event_card_hint(text: str) -> str | None:
    """Extract event card identifier (e.g., "UFC 315").

    Args:
        text: Stream name

    Returns:
        Event identifier if found, None otherwise
    """
    if not text:
        return None

    # UFC 315, UFC FN 123, etc.
    ufc_match = re.search(r"\b(ufc\s*(?:fn|fight\s*night)?\s*\d+)\b", text, re.IGNORECASE)
    if ufc_match:
        return ufc_match.group(1).upper().replace("  ", " ")

    # PFL 5, Bellator 300, etc.
    org_match = re.search(r"\b((?:pfl|bellator|one\s*fc)\s*\d+)\b", text, re.IGNORECASE)
    if org_match:
        return org_match.group(1).upper()

    # Boxing event names - check for boxing-specific keywords
    text_lower = text.lower()
    boxing_keywords = [
        "boxing",
        "pbc",
        "premier boxing",
        "top rank",
        "matchroom",
        "golden boy",
        "showtime boxing",
        "dazn boxing",
    ]
    if any(kw in text_lower for kw in boxing_keywords):
        # Try to extract fighter names or event name
        # For now, just return a generic hint
        return "BOXING_EVENT"

    return None


def detect_card_segment(text: str) -> str | None:
    """Detect card segment from stream name (UFC, MMA).

    Segments:
    - "early_prelims": Early prelims / pre-show
    - "prelims": Regular prelims / preliminary card
    - "main_card": Main card / main event
    - "combined": Prelims + Mains combined stream

    Examples:
        "UFC 324 (Prelims)" → "prelims"
        "Gaethje vs Pimblett (Early Prelims)" → "early_prelims"
        "UFC 324 - Gaethje vs. Pimblett" → None (defaults to main_card later)
        "UFC 324: Main English" → "main_card"

    Args:
        text: Stream name (original, not normalized - for accurate pattern matching)

    Returns:
        Segment code or None if no segment detected
    """
    if not text:
        return None

    segment = DetectionKeywordService.detect_card_segment(text)
    if segment:
        logger.debug("[CLASSIFY] Detected card segment '%s' from '%s'", segment, text[:50])
    return segment


def is_combat_sports_excluded(text: str) -> bool:
    """Check if stream should be excluded from combat sports matching.

    Excludes weigh-ins, press conferences, countdowns, and other non-event content.

    Args:
        text: Stream name

    Returns:
        True if stream should be excluded
    """
    if not text:
        return False

    is_excluded = DetectionKeywordService.is_excluded(text)
    if is_excluded:
        logger.debug("[CLASSIFY] Combat sports excluded: %s", text[:50])
    return is_excluded


def extract_fighters_from_event_card(text: str) -> tuple[str | None, str | None]:
    """Extract fighter names from an EVENT_CARD stream.

    Uses the same separator logic as team extraction but handles fighter-specific
    patterns like "Gaethje vs Pimblett" or "Gaethje v Pimblett".

    Args:
        text: Stream name (normalized)

    Returns:
        Tuple of (fighter1, fighter2)
    """
    if not text:
        return None, None

    # Find separator and extract fighters
    separator, sep_position = find_game_separator(text)
    if separator:
        fighter1, fighter2 = extract_teams_from_separator(text, separator, sep_position)

        # Clean up fighter names - strip segment suffixes and event prefixes
        fighter1 = _clean_fighter_name(fighter1) if fighter1 else None
        fighter2 = _clean_fighter_name(fighter2) if fighter2 else None

        if fighter1 or fighter2:
            return fighter1, fighter2

    return None, None


def _clean_fighter_name(name: str) -> str | None:
    """Clean extracted fighter name for UFC/MMA matching.

    Strips segment suffixes, event prefixes, and other noise specific to
    combat sports streams.

    Args:
        name: Raw extracted fighter name

    Returns:
        Cleaned fighter name or None if nothing remains
    """
    if not name:
        return None

    # Strip segment suffixes: (Prelims), (Main Card 1), etc.
    for pattern, _segment in DetectionKeywordService.get_card_segment_patterns():
        name = pattern.sub("", name)

    # Strip empty parentheses left after segment removal
    name = re.sub(r"\(\s*\)", "", name)

    # Strip UFC event number prefix: "324 - Gaethje" → "Gaethje"
    # Also handles "UFC 324 Gaethje"
    name = re.sub(r"^(?:ufc\s+)?\d+\s*[-:]?\s*", "", name, flags=re.IGNORECASE)

    # Strip "UFC" prefix
    name = re.sub(r"^ufc\s+", "", name, flags=re.IGNORECASE)

    # Strip channel prefixes like "LIVE EVENT 03 -"
    name = re.sub(r"^live\s+event\s+\d+\s*[-:]\s*", "", name, flags=re.IGNORECASE)

    # Strip time prefixes like "9PM"
    name = re.sub(r"^\d{1,2}\s*(?:AM|PM)\s*", "", name, flags=re.IGNORECASE)

    # Strip common noise words at start
    name = re.sub(r"^(?:main\s+english|english|prelims?)\s*:?\s*", "", name, flags=re.IGNORECASE)

    # Clean up whitespace and punctuation
    name = re.sub(r"[\s\-:]+$", "", name)
    name = re.sub(r"^[\s\-:]+", "", name)
    name = name.strip()

    # Must have at least 2 characters to be a valid fighter name
    if len(name) < 2:
        return None

    return name


# =============================================================================
# MAIN CLASSIFICATION
# =============================================================================


def detect_and_strip_feed_hint(
    text: str,
    home_terms: list[str],
    away_terms: list[str],
) -> tuple[str, str | None]:
    """Detect HOME/AWAY feed indicator in text and strip it.

    Searches for configurable terms using word boundary matching.
    Returns the cleaned text (token removed) and the feed hint.

    Args:
        text: Normalized stream text (used for team extraction)
        home_terms: Terms that indicate home feed (e.g., ["HOME"])
        away_terms: Terms that indicate away feed (e.g., ["AWAY"])

    Returns:
        Tuple of (cleaned_text, feed_hint) where feed_hint is "home", "away", or None
    """
    for term in home_terms:
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        if pattern.search(text):
            cleaned = pattern.sub("", text)
            cleaned = " ".join(cleaned.split())  # Normalize whitespace
            return cleaned, "home"

    for term in away_terms:
        pattern = re.compile(rf"\b{re.escape(term)}\b", re.IGNORECASE)
        if pattern.search(text):
            cleaned = pattern.sub("", text)
            cleaned = " ".join(cleaned.split())  # Normalize whitespace
            return cleaned, "away"

    return text, None


@dataclass
class _ClassifyContext:
    """Shared inputs threaded through the classification step cascade."""

    stream_name: str  # Original raw name (custom regex matches against this)
    text: str  # Normalized text with feed hint stripped
    normalized: NormalizedStream
    league_event_type: str | None
    event_league_sport: str | None
    custom_regex: CustomRegexConfig | None
    league_hint: str | list[str] | None
    sport_hint: str | list[str] | None
    feed_hint: str | None

    def make(self, category: StreamCategory, **extra) -> ClassifiedStream:
        """Build a ClassifiedStream with the shared hint fields pre-filled."""
        return ClassifiedStream(
            category=category,
            normalized=self.normalized,
            league_hint=self.league_hint,
            sport_hint=self.sport_hint,
            feed_hint=self.feed_hint,
            **extra,
        )


def _apply_custom_datetime_regex(
    stream_name: str,
    custom_regex: CustomRegexConfig,
    normalized: NormalizedStream,
) -> None:
    """Step 1b: Apply custom date/time regex to override built-in extraction.

    Uses ORIGINAL stream name (not normalized) for more flexible matching.
    Mutates ``normalized`` in place.
    """
    if custom_regex.date_enabled:
        custom_date = extract_date_with_custom_regex(stream_name, custom_regex)
        if custom_date:
            normalized.extracted_date = custom_date
            logger.debug(
                "[CLASSIFY] Custom date regex extracted: %s from '%s'",
                custom_date,
                stream_name[:50],
            )

    if custom_regex.time_enabled:
        custom_time = extract_time_with_custom_regex(stream_name, custom_regex)
        if custom_time:
            normalized.extracted_time = custom_time
            logger.debug(
                "[CLASSIFY] Custom time regex extracted: %s from '%s'",
                custom_time,
                stream_name[:50],
            )


def _resolve_hints(
    text: str,
    stream_name: str,
    custom_regex: CustomRegexConfig | None,
) -> tuple[str | list[str] | None, str | list[str] | None]:
    """Detect league and sport hints (useful for all categories).

    Includes step 1c: a custom league regex (matched against the ORIGINAL
    stream name for more flexible matching) overrides built-in detection.

    Returns:
        Tuple of (league_hint, sport_hint)
    """
    league_hint = detect_league_hint(text)
    sport_hint = detect_sport_hint(text)

    # Narrow umbrella hints using gender markers (W)/(M)
    # e.g., NCAAB with (W) → womens-college-basketball only
    if isinstance(league_hint, list) and len(league_hint) > 1:
        league_hint = _narrow_by_gender(league_hint, stream_name)

    if custom_regex and custom_regex.league_enabled:
        custom_league = extract_league_with_custom_regex(stream_name, custom_regex)
        if custom_league:
            league_hint = custom_league
            logger.debug(
                "[CLASSIFY] Custom league regex extracted: %s from '%s'",
                custom_league,
                stream_name[:50],
            )

    return league_hint, sport_hint


def _classify_event_card(ctx: _ClassifyContext) -> ClassifiedStream | None:
    """Step 2: Check for event card (combat sports).

    Guard: if sport hint identifies a non-combat sport, skip keyword-
    based event_card detection. This prevents user-defined EVENT_CARD
    keywords (e.g., "card", "main") from stealing team sports streams
    like "(Baseball)". The league_event_type override still takes
    priority — if the league is explicitly configured as event_card,
    the sport hint won't block it.
    """
    _event_card_sports = {"mma", "boxing"}
    sport_blocks_keywords = False
    if ctx.sport_hint is not None and ctx.league_event_type != "event_card":
        if isinstance(ctx.sport_hint, list):
            sport_blocks_keywords = not any(
                s.lower() in _event_card_sports for s in ctx.sport_hint
            )
        else:
            sport_blocks_keywords = ctx.sport_hint.lower() not in _event_card_sports
        if sport_blocks_keywords:
            logger.debug(
                "[CLASSIFY] Sport hint '%s' blocks event_card classification",
                ctx.sport_hint,
            )

    if sport_blocks_keywords or not is_event_card(ctx.text, ctx.league_event_type):
        return None

    event_hint = extract_event_card_hint(ctx.text)

    # Detect card segment (early_prelims, prelims, main_card, combined)
    # Use original stream name for more accurate pattern matching
    card_segment = detect_card_segment(ctx.stream_name)

    # Try custom regex for fighters first (if configured)
    custom_regex_used = False
    fighter1, fighter2 = None, None
    if ctx.custom_regex and ctx.custom_regex.fighters_enabled:
        fighter1, fighter2, success = extract_fighters_with_custom_regex(
            ctx.stream_name, ctx.custom_regex
        )
        if success:
            custom_regex_used = True
            logger.debug(
                "[CLASSIFY] Custom fighters regex matched: %s vs %s",
                fighter1,
                fighter2,
            )

    # Fallback to builtin extraction if custom regex didn't match
    if not fighter1 and not fighter2:
        fighter1, fighter2 = extract_fighters_from_event_card(ctx.text)

    # Try custom regex for event name (if configured)
    if ctx.custom_regex and ctx.custom_regex.event_name_enabled:
        custom_event_name = extract_event_name_with_custom_regex(
            ctx.stream_name, ctx.custom_regex
        )
        if custom_event_name:
            event_hint = custom_event_name
            custom_regex_used = True
            logger.debug(
                "[CLASSIFY] Custom event_name regex matched: %s", custom_event_name
            )

    return ctx.make(
        StreamCategory.EVENT_CARD,
        team1=fighter1,  # Fighter 1 (treated as team for matching)
        team2=fighter2,  # Fighter 2 (treated as team for matching)
        event_hint=event_hint,
        card_segment=card_segment,
        custom_regex_used=custom_regex_used,
    )


def _classify_racing_event(ctx: _ClassifyContext) -> ClassifiedStream | None:
    """Step 2.5: Check for racing events (F1, NASCAR, etc.).

    Racing leagues are configured with event_type="event" - there's no
    reliable text keyword, so this is purely a league_event_type check.
    The full normalized text becomes the event_hint for fuzzy matching
    against the race weekend's name/circuit (e.g., "Monaco Grand Prix").

    Racing streams don't follow "Team A vs Team B" naming. If the stream
    has a game separator (vs/@/at) with extractable team names (e.g.
    "SD at BAL"), it's a team-sport stream that's leaked into a
    racing-only league set - let it fall through to Step 4 instead.
    """
    if not is_racing(
        ctx.league_event_type, ctx.league_hint, ctx.sport_hint, ctx.event_league_sport
    ):
        return None

    sep, sep_position = find_game_separator(ctx.text)
    has_team_pattern = False
    if sep:
        sep_team1, sep_team2 = extract_teams_from_separator(ctx.text, sep, sep_position)
        if sep_team1 or sep_team2:
            # For "at"/"@" separators, a multi-word left part is a series
            # or race name (e.g. "NASCAR Cup Series at San Diego", or a
            # stream with "@ Jun 20" as a date marker), not a team abbrev.
            # Single-word left parts (e.g. "SD", "NYY") are real team codes.
            if sep.strip() in ("at", "@") and sep_team1 and len(sep_team1.split()) > 1:
                has_team_pattern = False
            else:
                has_team_pattern = True

    # Guard against hijacking a team-sport stream that leaked into a
    # racing-dominant group. A bare team name ("Maple Leafs") has no
    # separator, so the has_team_pattern check alone wouldn't catch it;
    # but if it carries a positive NON-racing sport hint (e.g. "NHL |
    # Maple Leafs" → "hockey"), that's strong evidence it isn't a race —
    # let it fall through to team matching. Racing has no reliable text
    # keyword, so we can't require positive racing evidence; we only veto
    # on a hint that actively disagrees (None never vetoes).
    hint_disagrees = ctx.sport_hint is not None and str(ctx.sport_hint).lower() != "racing"

    if has_team_pattern or hint_disagrees:
        return None

    return ctx.make(StreamCategory.RACING_EVENT, event_hint=ctx.text)


def _classify_tennis_match(ctx: _ClassifyContext) -> ClassifiedStream | None:
    """Step 2.6: Check for tennis matches ("Wimbledon: Zheng vs Norrie").

    Tennis leagues share event_type="event" with racing, so the racing
    step above is disabled for tennis groups via event_league_sport and
    this step catches the streams instead. Match streams carry a
    player-vs-player separator; the players are extracted with the same
    separator logic as team sports (surname-based matching happens in
    TennisMatcher). Court/round/day feeds ("Wimbledon Day #6 No 1
    Court") have no separator — they still classify TENNIS_MATCH with
    only an event_hint so the matcher can report a precise reason
    (court-feed matching is a planned phase 2).
    """
    if not is_tennis(
        ctx.league_event_type, ctx.league_hint, ctx.sport_hint, ctx.event_league_sport
    ):
        return None

    separator, sep_position = find_game_separator(ctx.text)
    if separator:
        team1, team2 = extract_teams_from_separator(ctx.text, separator, sep_position)
        # "at"/"@" with a multi-word left part is a tournament/day
        # label ("Wimbledon Second Round @ Jul 2"), not a player pair.
        if (
            team1
            and team2
            and not (separator.strip() in ("at", "@") and len(team1.split()) > 1)
        ):
            return ctx.make(
                StreamCategory.TENNIS_MATCH,
                team1=team1,
                team2=team2,
                separator_found=separator,
            )

    return ctx.make(StreamCategory.TENNIS_MATCH, event_hint=ctx.text)


def _classify_teams_custom_regex(ctx: _ClassifyContext) -> ClassifiedStream | None:
    """Step 3: Try custom regex for team extraction (if configured).

    Uses ORIGINAL stream name (not normalized) for intuitive pattern matching.
    """
    if not (ctx.custom_regex and ctx.custom_regex.teams_enabled):
        return None

    team1, team2, success = extract_teams_with_custom_regex(ctx.stream_name, ctx.custom_regex)
    if not success:
        return None

    return ctx.make(
        StreamCategory.TEAM_VS_TEAM,
        team1=team1,
        team2=team2,
        separator_found="custom_regex",
        custom_regex_used=True,
    )


def _classify_team_vs_team(ctx: _ClassifyContext) -> ClassifiedStream | None:
    """Step 4: Check for game separator (builtin fallback)."""
    separator, sep_position = find_game_separator(ctx.text)
    if not separator:
        return None

    team1, team2 = extract_teams_from_separator(ctx.text, separator, sep_position)

    # Only classify as TEAM_VS_TEAM if we got at least one team
    if not (team1 or team2):
        return None

    return ctx.make(
        StreamCategory.TEAM_VS_TEAM,
        team1=team1,
        team2=team2,
        separator_found=separator,
    )


def _classify_team_only(ctx: _ClassifyContext) -> ClassifiedStream | None:
    """Step 4.5: Check for single-team stream (TEAM_ONLY).

    Applies when no separator was found (would otherwise be PLACEHOLDER).
    A stream qualifies as TEAM_ONLY when:
      - No date or time was extracted (stream is not event-specific)
      - After stripping league/sport/noise prefixes, a non-trivial candidate remains
    The matcher validates the candidate against the team cache; a miss → NO_MATCH.
    """
    if ctx.normalized.extracted_date is not None or ctx.normalized.extracted_time is not None:
        return None

    candidate = _clean_team_name(ctx.text)
    if not candidate or len(candidate) < 3:
        return None

    return ctx.make(StreamCategory.TEAM_ONLY, team1=candidate)


# Ordered cascade: first step to return a result wins.
_CLASSIFY_STEPS = (
    _classify_event_card,
    _classify_racing_event,
    _classify_tennis_match,
    _classify_teams_custom_regex,
    _classify_team_vs_team,
    _classify_team_only,
)


def classify_stream(
    stream_name: str,
    league_event_type: str | None = None,
    custom_regex: CustomRegexConfig | None = None,
    feed_home_terms: list[str] | None = None,
    feed_away_terms: list[str] | None = None,
    event_league_sport: str | None = None,
) -> ClassifiedStream:
    """Classify a stream for matching strategy selection.

    Classification order (see the _classify_* step functions):
    1. Normalize stream name
    1b. Apply custom date/time regex (if configured) to override extracted values
    1c. Detect league/sport hints; custom league regex overrides detection
    2. Check for event card keywords/type → EVENT_CARD
    2.5. Racing group check → RACING_EVENT
    2.6. Tennis group check → TENNIS_MATCH
    3. Try custom regex for team extraction (if configured) → TEAM_VS_TEAM
    4. Check for game separator (vs/@/at) → TEAM_VS_TEAM
    4.5. Check for single-team content (no separator, no date/time) → TEAM_ONLY
    5. Default → PLACEHOLDER (can't classify)

    Note: Placeholder pattern detection is now handled by StreamFilter before
    streams reach the classifier. This classifier focuses purely on categorizing
    streams that have passed eligibility filtering.

    Args:
        stream_name: Raw stream name to classify
        league_event_type: Optional event_type from leagues table (e.g., "fight" for UFC)
        custom_regex: Optional custom regex configuration for team/date/time extraction
        event_league_sport: Dominant sport of the group's event-type leagues
            ("racing" | "tennis" | ...). Disambiguates the shared "event"
            league_event_type between the racing and tennis paths.

    Returns:
        ClassifiedStream with category and extracted info
    """
    # Step 1: Normalize
    normalized = normalize_stream(stream_name)

    if custom_regex:
        _apply_custom_datetime_regex(stream_name, custom_regex, normalized)

    # Early exit for empty streams
    if not normalized.normalized:
        result = ClassifiedStream(
            category=StreamCategory.PLACEHOLDER,
            normalized=normalized,
        )
    else:
        text = normalized.normalized

        # Detect and strip feed hint (HOME/AWAY) before team extraction
        # so tokens like "HOME" don't pollute team name matching
        feed_hint = None
        if feed_home_terms or feed_away_terms:
            text, feed_hint = detect_and_strip_feed_hint(
                text,
                feed_home_terms or [],
                feed_away_terms or [],
            )
            if feed_hint:
                logger.debug(
                    "[CLASSIFY] Feed hint '%s' detected and stripped from '%s'",
                    feed_hint,
                    stream_name[:50],
                )

        league_hint, sport_hint = _resolve_hints(text, stream_name, custom_regex)

        ctx = _ClassifyContext(
            stream_name=stream_name,
            text=text,
            normalized=normalized,
            league_event_type=league_event_type,
            event_league_sport=event_league_sport,
            custom_regex=custom_regex,
            league_hint=league_hint,
            sport_hint=sport_hint,
            feed_hint=feed_hint,
        )

        result = None
        for step in _CLASSIFY_STEPS:
            result = step(ctx)
            if result is not None:
                break

        # Step 5: Default to placeholder if we can't classify
        if result is None:
            result = ctx.make(StreamCategory.PLACEHOLDER)

    logger.debug(
        "[CLASSIFY] '%s' -> %s (league=%s, sport=%s, teams=%s/%s, segment=%s)",
        stream_name[:50],
        result.category.value,
        result.league_hint,
        result.sport_hint,
        result.team1,
        result.team2,
        result.card_segment,
    )

    return result


def classify_streams(
    stream_names: list[str],
    league_event_type: str | None = None,
    custom_regex: CustomRegexConfig | None = None,
    feed_home_terms: list[str] | None = None,
    feed_away_terms: list[str] | None = None,
    event_league_sport: str | None = None,
) -> list[ClassifiedStream]:
    """Classify multiple streams.

    Args:
        stream_names: List of raw stream names
        league_event_type: Optional event_type from leagues table
        custom_regex: Optional custom regex configuration for team extraction
        feed_home_terms: Terms indicating home feed (e.g., ["HOME"])
        feed_away_terms: Terms indicating away feed (e.g., ["AWAY"])
        event_league_sport: Dominant sport of the group's event-type leagues

    Returns:
        List of ClassifiedStream objects
    """
    return [
        classify_stream(
            name,
            league_event_type,
            custom_regex,
            feed_home_terms,
            feed_away_terms,
            event_league_sport,
        )
        for name in stream_names
    ]
