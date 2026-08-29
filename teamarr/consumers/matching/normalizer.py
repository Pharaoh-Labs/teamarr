"""Stream name normalization for matching.

Cleans up heterogeneous, poorly-formatted stream names before matching:
- Fixes mojibake (double-encoded UTF-8)
- Strips provider prefixes (ESPN+, DAZN, etc.)
- Applies city translations (München → Munich)
- Masks datetime patterns for separator detection
- Extracts date/time hints for validation
"""

import logging
import re
from dataclasses import dataclass
from datetime import date, time

from unidecode import unidecode

from teamarr.utilities.constants import (
    BROADCAST_NETWORKS,
    CITY_TRANSLATIONS,
    LIVE_STATUS_PREFIXES,
    PROVIDER_PREFIXES,
)

logger = logging.getLogger(__name__)


@dataclass
class NormalizedStream:
    """Result of stream normalization with extracted metadata."""

    original: str
    normalized: str

    # Extracted metadata (may be None)
    extracted_date: date | None = None
    # Whether the date's format is verified (#474): True for built-in
    # extraction and for custom regex with declared (month/day/year groups)
    # or learned formats; False when the date came from blind per-string
    # format guessing. Unverified dates rank candidates instead of gating them.
    extracted_date_trusted: bool = True
    extracted_time: time | None = None
    extracted_tz: str | None = None  # IANA timezone (e.g., 'America/New_York')
    league_hint: str | None = None
    provider_prefix: str | None = None


# =============================================================================
# MOJIBAKE DETECTION AND FIXING
# =============================================================================

# Common mojibake patterns (double-encoded UTF-8)
MOJIBAKE_PATTERNS = [
    # German umlauts
    (r"Ã¼", "ü"),
    (r"Ã¶", "ö"),
    (r"Ã¤", "ä"),
    (r"Ãœ", "Ü"),
    (r"Ã–", "Ö"),
    (r"Ã„", "Ä"),
    (r"ÃŸ", "ß"),
    # Spanish/Portuguese
    (r"Ã±", "ñ"),
    (r"Ã©", "é"),
    (r"Ã¡", "á"),
    (r"Ã­", "í"),
    (r"Ã³", "ó"),
    (r"Ãº", "ú"),
    (r"Ã§", "ç"),
    # French
    (r"Ã¨", "è"),
    (r"Ãª", "ê"),
    (r"Ã«", "ë"),
    (r"Ã®", "î"),
    (r"Ã¯", "i"),
    (r"Ã´", "o"),
    (r"Ã¹", "u"),
    (r"Ã»", "u"),
]


def try_fix_double_encoded(text: str) -> str:
    """Attempt to repair double-encoded UTF-8 text via a latin-1/utf-8 round trip.

    Mojibake like "MÃ¼nchen" (for "München") typically happens when UTF-8
    bytes get mis-decoded as latin-1 somewhere upstream (latin-1 is a
    lossless 1:1 byte<->codepoint mapping, so no information is lost -- it
    can be reversed). Reversing it means re-encoding the broken text back to
    latin-1 bytes, then decoding those bytes as UTF-8.

    This is intentionally conservative and safe to call on arbitrary,
    possibly-already-correct text: if the round trip raises (the text wasn't
    actually latin-1-of-utf8, e.g. legitimate "SÃO PAULO FC") or produces a
    U+FFFD replacement character (a silently swallowed decode error), the
    original text is returned unchanged rather than mangled. It is also
    idempotent -- re-running it on already-correct text is a no-op, since
    re-encoding proper unicode text as latin-1 generally fails or decoding
    the result as UTF-8 does.

    Args:
        text: Potentially double-encoded text

    Returns:
        The repaired text, or the original text unchanged if the round trip
        wasn't safely reversible.
    """
    if not text:
        return text

    try:
        candidate = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text

    if "�" in candidate:
        return text

    return candidate


def fix_mojibake(text: str) -> str:
    """Fix mojibake (double-encoded UTF-8) in text.

    Tries the generic, guarded latin-1/utf-8 round trip first
    (``try_fix_double_encoded``), which covers any double-encoded script
    (Nordic, Polish, etc.), not just the hard-coded patterns below. Falls
    back to the hard-coded MOJIBAKE_PATTERNS replacements when the generic
    round trip doesn't change anything, to preserve any prior behavior it
    doesn't cover.

    Args:
        text: Potentially mojibake'd text

    Returns:
        Fixed text with proper unicode characters
    """
    if not text:
        return text

    result = try_fix_double_encoded(text)
    if result == text:
        for pattern, replacement in MOJIBAKE_PATTERNS:
            result = result.replace(pattern, replacement)

    if result != text:
        logger.debug("[MOJIBAKE] Fixed: '%s' -> '%s'", text[:40], result[:40])

    return result


# =============================================================================
# PROVIDER PREFIX STRIPPING
# =============================================================================


def strip_provider_prefix(text: str) -> tuple[str, str | None]:
    """Remove provider prefix from stream name.

    Args:
        text: Stream name potentially with provider prefix

    Returns:
        Tuple of (cleaned text, removed prefix or None)
    """
    if not text:
        return text, None

    text_lower = text.lower()

    for prefix in PROVIDER_PREFIXES:
        if text_lower.startswith(prefix.lower()):
            return text[len(prefix) :].strip(), prefix.strip()

    return text, None


# Leading live-status token + any immediate separator noise (": ", " - ", "| ").
# The token requires a trailing word boundary (so a name merely starting with the
# letters is safe); the trailing class stops before a real team name, so a matchup
# separator further along ("DIRECTO España - Inglaterra") is left untouched.
_LIVE_STATUS_RE = re.compile(
    r"^(?:" + "|".join(re.escape(p) for p in LIVE_STATUS_PREFIXES) + r")\b[\s:|–—-]*",
    re.IGNORECASE,
)


def strip_live_status_prefix(text: str) -> tuple[str, str | None]:
    """Remove a leading live-broadcast status word from a stream name.

    "DIRECTO España - Inglaterra" -> ("España - Inglaterra", "DIRECTO")
    "Real Madrid - Barcelona"     -> ("Real Madrid - Barcelona", None)

    Args:
        text: Stream name potentially prefixed with a live-status word.

    Returns:
        Tuple of (cleaned text, removed token or None).
    """
    if not text:
        return text, None

    match = _LIVE_STATUS_RE.match(text)
    if not match:
        return text, None

    removed = text[: match.end()].strip()
    return text[match.end() :].strip(), removed


# =============================================================================
# CITY TRANSLATIONS
# =============================================================================


def apply_city_translations(text: str) -> str:
    """Apply city name translations.

    First normalizes with unidecode (München → Munchen),
    then applies manual translations (munchen → munich).

    Args:
        text: Text containing city names

    Returns:
        Text with city names translated to English
    """
    if not text:
        return text

    # First pass: unidecode to normalize accents
    # This converts München → Munchen
    text = unidecode(text)

    # Second pass: apply manual translations
    # Work on lowercased version for matching, preserve original case pattern
    result = text
    text_lower = text.lower()

    for variant, english in CITY_TRANSLATIONS.items():
        if variant in text_lower:
            # Find the position and replace preserving some case
            pattern = re.compile(re.escape(variant), re.IGNORECASE)
            result = pattern.sub(english, result)

    return result


# =============================================================================
# DATETIME EXTRACTION AND MASKING
# =============================================================================

# Date patterns to extract and mask
_MONTHS = r"Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"
# Abbrev or full month name, \b-anchored. Avoids the old `(Jan|...)[a-z]*`
# which let "Mar" swallow "Marauders" -> mis-read as "Mar 30".
_MONTH_NAMES = (
    r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
)
DATE_PATTERNS = [
    # ISO format: 2026-01-09 (YYYY-MM-DD) - must be before MM/DD/YYYY pattern
    (r"\b(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})\b", "DATE_MASK_ISO"),
    # 12/31/25, 12/31/2025 (MM/DD/YY or MM/DD/YYYY)
    (r"\b(\d{1,2})[/\-](\d{1,2})[/\-](\d{2,4})\b", "DATE_MASK"),
    # 30 @ Jun - reversed day-@-month tail (some MiLB feeds). Masking removes the
    # stray "@" so it can't beat " at " as the matchup separator. Month NAME
    # required so real matchups ("LAL @ BOS") are untouched.
    (rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s*@\s*(?:{_MONTH_NAMES})\b", "DATE_MASK"),
    # 1/17, 12/31 (MM/DD without year) - infer year based on proximity to today
    # Must come after MM/DD/YYYY to avoid partial matches
    (r"\b(\d{1,2})[/\-](\d{1,2})\b", "DATE_MASK_NO_YEAR"),
    # 31 Dec, 31 December - check this BEFORE "Dec 31" to prefer "14 Jan" over "Jan 11"
    (rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:{_MONTH_NAMES})\b", "DATE_MASK"),
    # Dec 31, December 31 - use negative lookahead (?!:) to avoid matching "Jan 11:45pm"
    (rf"\b(?:{_MONTH_NAMES})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?!:)\b", "DATE_MASK"),
    # 8.29, 08.29 (M.DD without year) — dot-separated dates (#652). Deliberately
    # LAST: masking happens whether or not the date parses, so a greedy pattern
    # here would eat text the forms above read correctly, and the loop breaks on
    # first match.
    #
    # Tightly bounded, because a dot between digits is usually NOT a date.
    # Measured over 1036 dot-numbers in real stream names: 1020 had a two-digit
    # day and every one was a date (08.27, 8.29); the one-digit-day cases were
    # noise ("5.1"), and "17.45"/"10.30" were TIMES written with a dot. So the
    # month is bounded 1-12 (killing 13.4 and 17.45), the day must be two digits
    # 01-31 (killing 5.1 and decimal spreads like "2.5"), and an am/pm suffix
    # vetoes the read so "10.30pm" stays a time.
    (r"\b(1[0-2]|0?[1-9])\.(3[01]|[12]\d|0[1-9])\b(?!\s*[ap]\.?m)", "DATE_MASK_NO_YEAR"),
]

# Time patterns to extract and mask (with optional TZ suffix)
# TZ pattern captures timezone abbreviations - comprehensive list for sports broadcasting
# Grouped by region for maintainability
_TZ_ABBREVS = (
    r"E[SD]?T|P[SD]?T|C[SD]?T|M[SD]?T"  # US/Canada main zones
    r"|AK[SD]?T|H[AS]T|A[SD]T|N[SD]?T"  # Alaska, Hawaii, Atlantic, Newfoundland
    r"|GMT|UTC|Z"  # Universal
    r"|BST|WET|WEST|IST|CET|CEST|MET|MEST|EET|EEST|MSK"  # Europe
    r"|AE[SD]T|AC[SD]T|AW[SD]?T|AET|ACT|AWT"  # Australia
    r"|JST|KST|HKT|SGT|MYT|GST"  # Asia
    r"|BRT|BRST|ART"  # South America
    r"|NZ[SD]?T|NZT"  # New Zealand
    r"|SAST"  # Africa
)
TIME_PATTERNS = [
    # 7:00 PM ET, 7:00PM EST, 19:00 GMT - time with optional TZ
    (rf"\b(\d{{1,2}}):(\d{{2}})(?::(\d{{2}}))?\s*(AM|PM|am|pm)?\s*({_TZ_ABBREVS})?\b", "TIME_MASK"),
    # 7PM ET, 7 PM EST
    (rf"\b(\d{{1,2}})\s*(AM|PM|am|pm)\s*({_TZ_ABBREVS})?\b", "TIME_MASK"),
]

# Standalone TZ pattern (after time has been masked, e.g., "@ ET" at end)
# \b guards the abbreviation: without it "Gomez", "Budapest" and "Stuttgart"
# lost their Z/EST/ART tails as a phantom timezone (#283).
TZ_STANDALONE_PATTERN = rf"\s*@?\s*\b({_TZ_ABBREVS})\s*$"

# Catchup/timeshift metadata some providers append to stream names (#495):
#   "Dodgers x Yankees start:2026-07-19 17:35:00 stop:2026-07-20 00:48:20"
# The start timestamp doubles as the stream's date/time, but the WHOLE tail has
# to go before separator/team detection: generic masking replaces only the
# first date+time, so the stop timestamp would survive and corrupt team
# extraction ("Yankees start:" reads as a show-name prefix, leaving
# team2="stop:2026-07-20 00:48:20").
CATCHUP_START_PATTERN = re.compile(
    r"\bstart\s*[:=]\s*(\d{4})-(\d{1,2})-(\d{1,2})[ T](\d{1,2}):(\d{2})(?::\d{2})?",
    re.IGNORECASE,
)
# Stop timestamp may be truncated by provider name-length limits ("stop:20"),
# so accept any digit-led date/time fragment after the label.
CATCHUP_STOP_PATTERN = re.compile(
    r"\bstop\s*[:=]\s*\d[\d/\-]*(?:[ T]\d{1,2}(?::\d{2}){0,2})?",
    re.IGNORECASE,
)

# Map timezone abbreviations to IANA timezone names
TZ_ABBREVIATION_MAP = {
    # === North America ===
    # US/Canada Eastern
    "ET": "America/New_York",
    "EST": "America/New_York",
    "EDT": "America/New_York",
    # US/Canada Central
    "CT": "America/Chicago",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    # US/Canada Mountain
    "MT": "America/Denver",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    # US/Canada Pacific
    "PT": "America/Los_Angeles",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    # Alaska
    "AKT": "America/Anchorage",
    "AKST": "America/Anchorage",
    "AKDT": "America/Anchorage",
    # Hawaii
    "HST": "Pacific/Honolulu",
    "HAT": "Pacific/Honolulu",
    # Atlantic (Canada)
    "AT": "America/Halifax",
    "AST": "America/Halifax",
    "ADT": "America/Halifax",
    # Newfoundland
    "NT": "America/St_Johns",
    "NST": "America/St_Johns",
    "NDT": "America/St_Johns",
    # === UTC/GMT ===
    "UTC": "UTC",
    "GMT": "UTC",
    "Z": "UTC",
    # === Europe ===
    # UK/Ireland
    "BST": "Europe/London",
    "WET": "Europe/London",
    "WEST": "Europe/London",
    "IST": "Europe/Dublin",  # Irish Standard Time (also India, context needed)
    # Central European
    "CET": "Europe/Paris",
    "CEST": "Europe/Paris",
    "MET": "Europe/Paris",
    "MEST": "Europe/Paris",
    # Eastern European
    "EET": "Europe/Athens",
    "EEST": "Europe/Athens",
    # Moscow
    "MSK": "Europe/Moscow",
    # === Australia ===
    # Eastern Australia
    "AET": "Australia/Sydney",
    "AEST": "Australia/Sydney",
    "AEDT": "Australia/Sydney",
    # Central Australia
    "ACT": "Australia/Adelaide",
    "ACST": "Australia/Adelaide",
    "ACDT": "Australia/Adelaide",
    # Western Australia
    "AWT": "Australia/Perth",
    "AWST": "Australia/Perth",
    # === Asia ===
    # Japan
    "JST": "Asia/Tokyo",
    # Korea
    "KST": "Asia/Seoul",
    # China
    "CST_CN": "Asia/Shanghai",  # Differentiate from US Central
    "HKT": "Asia/Hong_Kong",
    # Singapore/Malaysia
    "SGT": "Asia/Singapore",
    "MYT": "Asia/Kuala_Lumpur",
    # India
    "IST_IN": "Asia/Kolkata",  # Differentiate from Irish
    # Middle East
    "GST": "Asia/Dubai",  # Gulf Standard Time
    # === South America ===
    # Brazil
    "BRT": "America/Sao_Paulo",
    "BRST": "America/Sao_Paulo",
    # Argentina
    "ART": "America/Buenos_Aires",
    # === New Zealand ===
    "NZT": "Pacific/Auckland",
    "NZST": "Pacific/Auckland",
    "NZDT": "Pacific/Auckland",
    # === South Africa ===
    "SAST": "Africa/Johannesburg",
}


def extract_and_mask_datetime(text: str) -> tuple[str, date | None, time | None, str | None]:
    """Extract date/time/timezone from stream name and mask for separator detection.

    Masking prevents date components like "12/31" from being mistaken
    for score patterns or other separators.

    Args:
        text: Stream name

    Returns:
        Tuple of (masked text, extracted date, extracted time, extracted tz as IANA name)
    """
    if not text:
        return text, None, None, None

    result = text

    # Normalize em dashes (—) and en dashes (–) to spaces for pattern matching
    result = result.replace("\u2014", " ").replace("\u2013", " ")

    extracted_date = None
    extracted_time = None
    extracted_tz = None

    # Catchup metadata (#495): take date/time from the start timestamp, then
    # strip both start and stop labels entirely.
    catchup_match = CATCHUP_START_PATTERN.search(result)
    if catchup_match:
        try:
            year, month, day, hour, minute = (int(g) for g in catchup_match.groups())
            extracted_date = date(year, month, day)
            extracted_time = time(hour, minute)
        except ValueError:
            pass
        result = CATCHUP_START_PATTERN.sub(" ", result)
    result = CATCHUP_STOP_PATTERN.sub(" ", result)

    # Extract and mask dates
    for pattern, mask in DATE_PATTERNS:
        match = re.search(pattern, result, re.IGNORECASE)
        if match:
            is_iso = mask == "DATE_MASK_ISO"
            no_year = mask == "DATE_MASK_NO_YEAR"
            if extracted_date is None:
                extracted_date = _parse_date_match(match, is_iso=is_iso, no_year=no_year)
            result = re.sub(pattern, " DATE_MASK ", result, count=1, flags=re.IGNORECASE)
            break

    # Extract and mask times (with optional TZ)
    for pattern, mask in TIME_PATTERNS:
        match = re.search(pattern, result, re.IGNORECASE)
        if match:
            parsed_time, parsed_tz = _parse_time_match(match)
            if extracted_time is None:
                extracted_time = parsed_time
            extracted_tz = extracted_tz or parsed_tz
            result = re.sub(pattern, f" {mask} ", result, count=1, flags=re.IGNORECASE)
            break

    # If no TZ from time, check for standalone TZ (e.g., "@ ET" at end)
    if not extracted_tz:
        tz_match = re.search(TZ_STANDALONE_PATTERN, result, re.IGNORECASE)
        if tz_match:
            tz_abbrev = tz_match.group(1).upper()
            extracted_tz = TZ_ABBREVIATION_MAP.get(tz_abbrev)
            # Remove the standalone TZ from result
            result = re.sub(TZ_STANDALONE_PATTERN, "", result, flags=re.IGNORECASE)

    # Clean up multiple spaces
    result = " ".join(result.split())

    return result, extracted_date, extracted_time, extracted_tz


def _parse_date_match(match: re.Match, is_iso: bool = False, no_year: bool = False) -> date | None:
    """Parse a date from regex match.

    Args:
        match: Regex match object
        is_iso: True if pattern matched ISO format (YYYY-MM-DD)
        no_year: True if pattern matched MM/DD without year (infer year)
    """
    try:
        groups = match.groups()
        text = match.group(0)

        # Check if it's a month name pattern
        month_names = {
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }

        for month_abbr, month_num in month_names.items():
            if month_abbr in text.lower():
                # Extract day number
                day_match = re.search(r"(\d{1,2})", text)
                if day_match:
                    day = int(day_match.group(1))
                    return _infer_year_for_date(month_num, day)
                return None

        # MM/DD without year - infer year based on proximity to today
        if no_year and len(groups) >= 2:
            month = int(groups[0])
            day = int(groups[1])
            return _infer_year_for_date(month, day)

        # Numeric date patterns with year
        if len(groups) >= 3:
            if is_iso:
                # ISO format: YYYY-MM-DD
                year = int(groups[0])
                month = int(groups[1])
                day = int(groups[2])
            else:
                # US format: MM/DD/YY or MM/DD/YYYY
                month = int(groups[0])
                day = int(groups[1])
                year = int(groups[2])

                # Handle 2-digit year
                if year < 100:
                    year += 2000 if year < 50 else 1900

            return date(year, month, day)

    except (ValueError, IndexError, TypeError):
        pass

    return None


def _infer_year_for_date(month: int, day: int) -> date | None:
    """Infer the year for a MM/DD date based on proximity to today.

    For sports streams, prefer dates in the near future over past.
    If the date in current year is more than 6 months ago, assume next year.
    """
    from datetime import datetime

    today = datetime.now().date()
    current_year = today.year

    try:
        # Try current year first
        candidate = date(current_year, month, day)

        # If more than 6 months in the past, try next year
        days_ago = (today - candidate).days
        if days_ago > 180:
            candidate = date(current_year + 1, month, day)
        # If more than 6 months in the future, try previous year
        elif days_ago < -180:
            candidate = date(current_year - 1, month, day)

        return candidate
    except ValueError:
        # Invalid date (e.g., Feb 30)
        return None


def _parse_time_match(match: re.Match) -> tuple[time | None, str | None]:
    """Parse a time and optional timezone from regex match.

    Returns:
        Tuple of (time, tz_iana_name)
    """
    try:
        groups = match.groups()

        hour = int(groups[0])

        # Check for minutes
        minute = 0
        if len(groups) > 1 and groups[1] and groups[1].isdigit():
            minute = int(groups[1])

        # Check for AM/PM and TZ
        am_pm = None
        tz_abbrev = None
        for g in groups:
            if not g:
                continue
            g_upper = g.upper()
            if g_upper in ("AM", "PM"):
                am_pm = g_upper
            elif g_upper in TZ_ABBREVIATION_MAP:
                tz_abbrev = g_upper

        # Convert to 24-hour
        if am_pm == "PM" and hour < 12:
            hour += 12
        elif am_pm == "AM" and hour == 12:
            hour = 0

        # Convert TZ abbreviation to IANA name
        tz_iana = TZ_ABBREVIATION_MAP.get(tz_abbrev) if tz_abbrev else None

        return time(hour, minute), tz_iana

    except (ValueError, IndexError, TypeError):
        pass

    return None, None


# =============================================================================
# MAIN NORMALIZATION PIPELINE
# =============================================================================


def normalize_stream(stream_name: str) -> NormalizedStream:
    """Full normalization pipeline for stream names.

    Applies all normalization steps in order:
    1. Fix mojibake (double-encoded UTF-8)
    2. Strip provider and live-status prefixes
    3. Apply city translations (with unidecode)
    4. Extract and mask datetime
    5. Clean whitespace

    Args:
        stream_name: Raw stream name from M3U

    Returns:
        NormalizedStream with cleaned text and extracted metadata
    """
    if not stream_name:
        return NormalizedStream(
            original=stream_name or "",
            normalized="",
        )

    original = stream_name

    # Step 0: Normalize newlines to spaces (some streams have literal newlines)
    text = re.sub(r"[\r\n]+", " ", stream_name)

    # Step 1: Fix mojibake
    text = fix_mojibake(text)

    # Step 2: Strip leading provider and live-status prefixes. Loop because they
    # stack in either order ("DIRECTO DAZN ...", "DAZN EN DIRECTO ..."); keep the
    # first provider seen for metadata.
    provider_prefix: str | None = None
    for _ in range(3):
        text, found_provider = strip_provider_prefix(text)
        if found_provider and provider_prefix is None:
            provider_prefix = found_provider
        text, found_live = strip_live_status_prefix(text)
        if not found_provider and not found_live:
            break

    # Step 3: Apply city translations (includes unidecode)
    text = apply_city_translations(text)

    # Step 4: Extract and mask datetime (including timezone)
    text, extracted_date, extracted_time, extracted_tz = extract_and_mask_datetime(text)

    # Step 5: Clean whitespace and normalize
    text = " ".join(text.split())
    text = text.strip()

    logger.debug(
        "[NORMALIZE] '%s' -> '%s' (date=%s, time=%s, tz=%s, prefix=%s)",
        original[:60],
        text[:60],
        extracted_date,
        extracted_time,
        extracted_tz,
        provider_prefix,
    )

    return NormalizedStream(
        original=original,
        normalized=text,
        extracted_date=extracted_date,
        extracted_time=extracted_time,
        extracted_tz=extracted_tz,
        provider_prefix=provider_prefix,
    )


def normalize_for_matching(text: str) -> str:
    """Quick normalization for matching (no metadata extraction).

    Use this for normalizing team names or event names before comparison.
    Applies: unidecode, city translations, lowercase, strip punctuation,
    and removes broadcast network names that add noise to fuzzy matching.

    Args:
        text: Text to normalize

    Returns:
        Normalized lowercase text
    """
    if not text:
        return ""

    # Unidecode and city translations
    text = apply_city_translations(text)

    # Lowercase
    text = text.lower()

    # Remove broadcast network names (ESPN, FOX, etc.) that add noise
    # These appear in streams like "MIL Bucks ( ESPN Feed )"
    for network in BROADCAST_NETWORKS:
        text = re.sub(rf"\b{re.escape(network.lower())}\b", " ", text)

    # Remove apostrophes/backticks WITHOUT adding a space, exactly as
    # normalize_text does (#653). These two normalizers run in sequence —
    # _match_against_events calls this one, then _score_teams_against_event
    # calls normalize_text on the result — so a disagreement here is
    # unrecoverable downstream. Turning the apostrophe into a space split
    # "Hawai'i" into "hawai i", which shares no token with "hawaii rainbow
    # warriors": 46.7 against the 100.0 a single normalizer scores, below
    # BOTH_TEAMS_THRESHOLD, so the whole event was rejected. Same for
    # "American Int'l" and "G'town Col". unidecode has already run via
    # apply_city_translations, so a curly ’ is a plain \x27 by now.
    # Hex escapes avoid source-encoding ambiguity: \x27=apostrophe, \x60=backtick.
    text = re.sub("[\x27\x60]", "", text)

    # Remove punctuation except spaces (hyphens become spaces for matching)
    text = re.sub(r"[^\w\s]", " ", text)

    # Normalize whitespace
    text = " ".join(text.split())

    return text.strip()
