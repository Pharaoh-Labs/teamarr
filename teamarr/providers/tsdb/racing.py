"""Racing event parsing for TSDB provider.

TheSportsDB models a motorsport race weekend as several flat,
per-session events (Free Practice 1, Qualifying, Race, ...) that share a
season/round. This module groups those flat events back into the
`Event(sessions=[...], circuit_name=...)` shape the racing pipeline expects
(mirrors `teamarr.providers.espn.tournament` for ESPN-backed leagues).
"""

import logging
import re
from datetime import UTC, datetime

from teamarr.core import Event, EventStatus, RacingSession, Team, Venue

logger = logging.getLogger(__name__)

# Keywords that mark a TSDB event as a non-race session (practice,
# qualifying, etc). The event in a group whose name contains none of these
# is the race itself.
_SESSION_KEYWORDS_RE = re.compile(
    r"practice|qualifying|hyperpole|warm|prologue|fp\d|session", re.IGNORECASE
)

_FREE_PRACTICE_RE = re.compile(r"^(?:free practice|fp)\s*(\d+)$", re.IGNORECASE)
_WARMUP_RE = re.compile(r"^warm[\s-]?up$", re.IGNORECASE)
_QUALIFYING_RE = re.compile(
    r"^(?:hyperpole\s+)?qualifying(?:\s*[-–]\s*(.+))?$", re.IGNORECASE
)
_HYPERPOLE_RE = re.compile(
    r"^hyperpole\s*(\d*)\s*(?:[-–]\s*(.+))?$", re.IGNORECASE
)
_PROLOGUE_RE = re.compile(r"prologue", re.IGNORECASE)


def _slugify(text: str) -> str:
    """Lowercase and replace non-alphanumeric runs with underscores."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _parse_session_label(event_name: str, race_name: str | None) -> tuple[str, str]:
    """Map a TSDB racing event name to a `(session_code, session_name)` pair.

    `race_name` is the event name identified as the race itself (if any); an
    exact match short-circuits to `("race", "Race")`, and is also stripped as
    a prefix from other event names in the group before classification.
    """
    if race_name and event_name == race_name:
        return "race", "Race"

    label = event_name
    if race_name and event_name.startswith(race_name):
        label = event_name[len(race_name):].strip()

    if match := _FREE_PRACTICE_RE.match(label):
        num = match.group(1)
        return f"fp{num}", f"Practice {num}"

    if _WARMUP_RE.match(label):
        return "warmup", "Warm Up"

    if match := _QUALIFYING_RE.match(label):
        class_part = (match.group(1) or "").strip()
        if class_part:
            return f"qualifying_{_slugify(class_part)}", f"Qualifying - {class_part}"
        return "qualifying", "Qualifying"

    if match := _HYPERPOLE_RE.match(label):
        num = match.group(1) or ""
        class_part = (match.group(2) or "").strip()
        code = "hyperpole"
        name = "Hyperpole"
        if num:
            code += f"_{num}"
            name += f" {num}"
        if class_part:
            code += f"_{_slugify(class_part)}"
            name += f" - {class_part}"
        return code, name

    if _PROLOGUE_RE.search(label):
        if "afternoon" in label.lower():
            return "prologue_pm", "Prologue (PM)"
        if "morning" in label.lower():
            return "prologue_am", "Prologue (AM)"

    slug = _slugify(label) or "race"
    return slug, label.title()


def _parse_datetime(
    date_str: str | None, time_str: str | None, timestamp_str: str | None
) -> datetime | None:
    """Parse a TSDB event's date/time fields into a UTC datetime."""
    if timestamp_str:
        try:
            if timestamp_str.endswith("Z"):
                return datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            dt = datetime.fromisoformat(timestamp_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            pass

    if date_str:
        try:
            dt_str = f"{date_str}T{time_str}" if time_str else date_str
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=UTC)
            return dt
        except ValueError:
            pass

    return None


def _make_abbrev(name: str) -> str:
    """Make an abbreviation for an event name (e.g. event group placeholder team)."""
    words = [w for w in name.split() if len(w) > 2]
    if len(words) >= 2:
        return "".join(w[0].upper() for w in words[:4])
    return name[:6].upper()


def _parse_venue(data: dict) -> Venue | None:
    venue_name = data.get("strVenue")
    if not venue_name:
        return None
    return Venue(
        name=venue_name, city=data.get("strCity"), state=None, country=data.get("strCountry")
    )


def _is_race_event(event_name: str) -> bool:
    """True if a TSDB event name has no session-type keywords (i.e. it's the race)."""
    return not _SESSION_KEYWORDS_RE.search(event_name)


def parse_racing_events(
    events: list[dict], league: str, sport: str, provider_name: str
) -> list[Event]:
    """Group TSDB's flat per-session events into multi-session racing `Event`s.

    Groups raw `eventsseason.php` event dicts by `(strSeason, intRound)`, then
    builds one `Event` per group with `sessions` populated from each event in
    the group (see `_parse_session_label`).
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for event_data in events:
        season = str(event_data.get("strSeason") or "")
        round_ = str(event_data.get("intRound") or "")
        groups.setdefault((season, round_), []).append(event_data)

    parsed_events = []
    for (season, round_), group in groups.items():
        event = _parse_round_group(group, season, round_, league, sport, provider_name)
        if event:
            parsed_events.append(event)

    parsed_events.sort(key=lambda e: e.start_time)
    return parsed_events


def _event_start_time(event_data: dict) -> datetime | None:
    return _parse_datetime(
        event_data.get("dateEvent"), event_data.get("strTime"), event_data.get("strTimestamp")
    )


def _parse_round_group(
    group: list[dict], season: str, round_: str, league: str, sport: str, provider_name: str
) -> Event | None:
    ordered = sorted(group, key=lambda e: _event_start_time(e) or datetime.min.replace(tzinfo=UTC))

    race_event = next((e for e in ordered if _is_race_event(e.get("strEvent", ""))), None)
    primary = race_event or ordered[-1]
    race_name = race_event.get("strEvent") if race_event else None

    sessions = []
    for event_data in ordered:
        start_time = _event_start_time(event_data)
        if not start_time:
            continue
        code, name = _parse_session_label(event_data.get("strEvent", ""), race_name)
        sessions.append(RacingSession(code=code, name=name, start_time=start_time, results=[]))

    if not sessions:
        return None

    sessions.sort(key=lambda s: s.start_time)

    event_id = f"tsdb_{league}_{season}_{round_}"
    name = primary.get("strEvent", "")
    venue = _parse_venue(primary)

    event_team = Team(
        id=f"event_{event_id}",
        provider=provider_name,
        name=name,
        short_name=name[:20],
        abbreviation=_make_abbrev(name),
        league=league,
        sport=sport,
        logo_url=None,
        color=None,
    )

    return Event(
        id=event_id,
        provider=provider_name,
        name=name,
        short_name=name,
        start_time=sessions[0].start_time,
        home_team=event_team,
        away_team=event_team,
        status=EventStatus(state="scheduled"),
        league=league,
        sport=sport,
        venue=venue,
        broadcasts=[],
        circuit_name=venue.name if venue else None,
        sessions=sessions,
    )
