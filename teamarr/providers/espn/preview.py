"""Parse ESPN summary facts into typed, public ``Event`` fields.

Only source-grounded pregame facts are read. Pickcenter, odds and predictor
payloads are deliberately outside every code path in this module.
"""

import re
from typing import Any

from teamarr.core import Event

_LEADER_FIELDS = {
    "baseball": {
        "homeRuns": ("home_runs_leader", "home runs"),
        "avg": ("batting_average_leader", "batting average"),
        "RBIs": ("rbi_leader", "RBI"),
    },
    "football": {
        "passingYards": ("passing_leader", "passing yards"),
        # Some ESPN payloads provide a fully formatted stat line (for example
        # "19/31, 181 YDS") under the *Leader names.  Do not append another
        # label to those already self-describing values.
        "passingLeader": ("passing_leader", ""),
        "rushingYards": ("rushing_leader", "rushing yards"),
        "rushingLeader": ("rushing_leader", ""),
        "receivingYards": ("receiving_leader", "receiving yards"),
        "receivingLeader": ("receiving_leader", ""),
    },
    "basketball": {
        "pointsPerGame": ("points_leader", "points per game"),
        "reboundsPerGame": ("rebounds_leader", "rebounds per game"),
        "assistsPerGame": ("assists_leader", "assists per game"),
    },
}

_TEAM_STAT_FIELDS = {
    "football": {
        "yardsPerGame": "total_yards_per_game",
        "rushingYardsPerGame": "rushing_yards_per_game",
    },
    "basketball": {
        "avgPoints": "team_ppg",
        "avgPointsAgainst": "points_allowed_per_game",
    },
}


def _team_side(event: Event, team_id: str) -> str | None:
    if team_id == str(event.home_team.id):
        return "home"
    if team_id == str(event.away_team.id):
        return "away"
    return None


def _display_value(item: dict) -> str:
    value = item.get("displayValue")
    return "" if value in (None, "") else str(value)


def _stat_map(items: list[dict] | None) -> dict[str, str]:
    return {
        str(item.get("name")): _display_value(item)
        for item in items or []
        if item.get("name") and _display_value(item)
    }


def _flatten_team_stats(items: list[dict] | None) -> dict[str, str]:
    """Flatten both ESPN's grouped baseball and flat team-stat shapes."""
    stats: dict[str, str] = {}
    for item in items or []:
        nested = item.get("stats")
        if nested is not None:
            stats.update(_stat_map(nested))
        elif item.get("name") and _display_value(item):
            stats[str(item["name"])] = _display_value(item)
    return stats


def _format_leader(name: str, value: str, label: str) -> str:
    if not name or not value:
        return ""
    # Some football categories contain a complete ESPN stat line rather than
    # bare yardage. Keep that provider value intact for the public variable;
    # the generated-prose formatter expands its abbreviations for readability.
    if label.endswith("yards") and re.search(r"\b(?:YDS?|yards?)\b", value, re.IGNORECASE):
        label = ""
    detail = f"{value} {label}".strip()
    return f"{name} — {detail}"


def _format_probable(probable: dict) -> str:
    athlete = probable.get("athlete") or {}
    name = athlete.get("displayName") or ""
    if not name:
        return ""
    stats = _stat_map(
        ((probable.get("statistics") or {}).get("splits") or {}).get("categories")
    )
    details = []
    if stats.get("wins") and stats.get("losses"):
        details.append(f"{stats['wins']}-{stats['losses']}")
    if stats.get("ERA"):
        details.append(f"{stats['ERA']} ERA")
    return f"{name} ({', '.join(details)})" if details else name


def _parse_week(raw: Any) -> int | None:
    if isinstance(raw, dict):
        raw = raw.get("number") or raw.get("value")
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _leader_blocks(data: dict, competition: dict) -> list[dict]:
    """Return summary leaders, falling back to competitor-scoped leaders."""
    if data.get("leaders"):
        return data["leaders"]
    blocks = []
    for competitor in competition.get("competitors") or []:
        if competitor.get("leaders"):
            blocks.append(
                {
                    "team": competitor.get("team") or {},
                    "leaders": competitor["leaders"],
                }
            )
    return blocks


def is_series_state(summary: object) -> bool:
    """Whether a series summary states where the series stands.

    ESPN fills the field for a series that has not begun with its start date
    ("Series starts 12/16") — a schedule note, and for a regular-season game
    months before that date, noise in the guide. Only real state counts
    ("Series tied 1-1", "BOS leads series 3-2").
    """
    text = str(summary or "").strip()
    return bool(text) and not text.lower().startswith("series starts")


def select_series(series_list: list[dict], event_id: str | None = None) -> dict | None:
    """Select the active/relevant series entry from a seasonseries list.

    Prioritizes:
    1. Series whose events explicitly contain event_id
    2. Active playoff series (type in ('playoff', 'postseason') and not completed)
    3. Any playoff series (type in ('playoff', 'postseason'))
    4. Series with type == 'current'
    5. Any uncompleted series (not completed)
    6. Series with type == 'season'
    7. First candidate with a non-empty summary
    """
    candidates = [
        item
        for item in series_list
        if isinstance(item, dict)
        and item.get("type") != "preseason"
        and is_series_state(item.get("summary"))
    ]
    if not candidates:
        return None

    if event_id:

        def _has_event(item: dict) -> bool:
            for ev in item.get("events") or []:
                if isinstance(ev, dict) and str(ev.get("id")) == str(event_id):
                    return True
                if isinstance(ev, str) and str(ev) == str(event_id):
                    return True
            return False

        matched = next((item for item in candidates if _has_event(item)), None)
        if matched:
            return matched

    matched = next(
        (
            item
            for item in candidates
            if item.get("type") in ("playoff", "postseason") and not item.get("completed", False)
        ),
        None,
    )
    if matched:
        return matched

    matched = next(
        (item for item in candidates if item.get("type") in ("playoff", "postseason")),
        None,
    )
    if matched:
        return matched

    matched = next((item for item in candidates if item.get("type") == "current"), None)
    if matched:
        return matched

    matched = next((item for item in candidates if not item.get("completed", False)), None)
    if matched:
        return matched

    matched = next((item for item in candidates if item.get("type") == "season"), None)
    if matched:
        return matched

    return candidates[0]


def apply_generated_preview_fields(data: dict[str, Any], event: Event) -> None:
    """Populate typed preview fields on ``event`` from an ESPN summary."""
    competition = ((data.get("header") or {}).get("competitions") or [{}])[0]
    header = data.get("header") or {}
    event.week = _parse_week(header.get("week") or competition.get("week"))

    for competitor in competition.get("competitors") or []:
        side = competitor.get("homeAway")
        if side not in {"home", "away"}:
            continue
        record = next(
            (
                item.get("summary") or item.get("displayValue")
                for item in competitor.get("record") or competitor.get("records") or []
                if item.get("type") in {"total", "overall"}
            ),
            "",
        )
        if record:
            setattr(event, f"{side}_team_record", str(record))
        probable = next(
            (item for item in competitor.get("probables") or [] if item.get("athlete")),
            None,
        )
        if event.sport == "baseball" and probable:
            setattr(event, f"{side}_probable_starter", _format_probable(probable))

    leader_contract = _LEADER_FIELDS.get(event.sport, {})
    for block in _leader_blocks(data, competition):
        side = _team_side(event, str((block.get("team") or {}).get("id") or ""))
        if not side:
            continue
        for category in block.get("leaders") or []:
            mapping = leader_contract.get(category.get("name"))
            leader = (category.get("leaders") or [{}])[0]
            athlete = leader.get("athlete") or {}
            if not mapping:
                continue
            suffix, label = mapping
            rendered = _format_leader(
                athlete.get("displayName") or "",
                _display_value(leader),
                label,
            )
            if rendered:
                setattr(event, f"{side}_{suffix}", rendered)

    stat_contract = _TEAM_STAT_FIELDS.get(event.sport, {})
    for block in (data.get("boxscore") or {}).get("teams") or []:
        side = _team_side(event, str((block.get("team") or {}).get("id") or ""))
        if not side:
            continue
        stats = _flatten_team_stats(block.get("statistics"))
        for espn_name, suffix in stat_contract.items():
            if stats.get(espn_name):
                setattr(event, f"{side}_{suffix}", stats[espn_name])

    series = select_series(data.get("seasonseries") or [], getattr(event, "id", None))
    if series and series.get("summary"):
        # Raw provider text — {series_summary} is a public variable and public
        # variables are never rewritten by our code (#613). The prose builder
        # expands team codes for readability on its own copy.
        event.series_summary = str(series["summary"])
