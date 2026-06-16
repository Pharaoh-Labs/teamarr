"""Read-only status helpers for static Teamarr team channels."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from xml.etree import ElementTree as ET


def parse_xmltv_timestamp(value: str | None) -> datetime | None:
    """Parse XMLTV timestamps like ``20260610014500 +0000`` as UTC datetimes."""
    if not value:
        return None

    raw = value.strip()
    if len(raw) < 14:
        return None

    base = raw[:14]
    offset = raw[15:].strip() if len(raw) > 15 else "+0000"

    try:
        parsed = datetime.strptime(f"{base}{offset}", "%Y%m%d%H%M%S%z")
    except ValueError:
        try:
            parsed = datetime.strptime(base, "%Y%m%d%H%M%S").replace(tzinfo=UTC)
        except ValueError:
            return None

    return parsed.astimezone(UTC)


def _text(element: ET.Element, name: str) -> str | None:
    child = element.find(name)
    if child is None or child.text is None:
        return None
    text = child.text.strip()
    return text or None


def _has_live_tag(element: ET.Element) -> bool:
    """True if the programme carries an explicit XMLTV ``<live/>`` tag."""
    return element.find("live") is not None


# Categories that mark a real game/event programme (as opposed to filler, which
# carries no category by default). "sports" is Teamarr's DEFAULT category
# (database/templates.py xmltv_categories=["Sports"]) and the live tag is OFF by
# default, so without recognising "sports" the endpoint would never find a
# window on a stock setup. The remaining entries cover common custom variants.
_EVENT_CATEGORIES = {"sports", "sport", "sports event", "live-sport", "live sport"}


def _is_event_programme(element: ET.Element) -> bool:
    """True if the programme is an actual game window (live tag or sports category)."""
    if _has_live_tag(element):
        return True

    categories = {
        (category.text or "").strip().lower()
        for category in element.findall("category")
        if category.text
    }
    return bool(categories & _EVENT_CATEGORIES)


def find_next_live_window(
    xmltv_content: str | None,
    channel_id: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return the current or next live programme for a team channel."""
    if not xmltv_content or not channel_id:
        return None

    now = (now or datetime.now(UTC)).astimezone(UTC)

    try:
        root = ET.fromstring(xmltv_content)
    except ET.ParseError:
        return None

    candidates: list[dict[str, Any]] = []
    for programme in root.findall("programme"):
        if programme.attrib.get("channel") != channel_id:
            continue

        start = parse_xmltv_timestamp(programme.attrib.get("start"))
        stop = parse_xmltv_timestamp(programme.attrib.get("stop"))
        if stop is not None and stop < now:
            continue
        if not _is_event_programme(programme):
            continue

        candidates.append(
            {
                "found": True,
                "start": start,
                "stop": stop,
                "title": _text(programme, "title"),
                "sub_title": _text(programme, "sub-title"),
                "is_live": _has_live_tag(programme),
                "source": "team_epg_xmltv",
            }
        )

    candidates.sort(
        key=lambda item: item["start"] or datetime.max.replace(tzinfo=UTC)
    )
    return candidates[0] if candidates else None


def build_team_channel_status(
    team: dict[str, Any],
    dispatcharr_channel: Any | None,
    xmltv_content: str | None,
    xmltv_updated_at: str | datetime | None = None,
    dispatcharr_error: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the API response payload for a static team channel."""
    next_live_window = find_next_live_window(
        xmltv_content,
        channel_id=team.get("channel_id", ""),
        now=now,
    )

    dispatcharr_payload = {"found": False, "error": dispatcharr_error}
    if dispatcharr_channel is not None:
        streams = list(getattr(dispatcharr_channel, "streams", ()) or ())
        dispatcharr_payload = {
            "found": True,
            "id": getattr(dispatcharr_channel, "id", None),
            "uuid": getattr(dispatcharr_channel, "uuid", None),
            "name": getattr(dispatcharr_channel, "name", None),
            "channel_number": getattr(dispatcharr_channel, "channel_number", None),
            "tvg_id": getattr(dispatcharr_channel, "tvg_id", None),
            "stream_count": len(streams),
            "streams": streams,
            "error": None,
        }

    programme_payload = next_live_window or {
        "found": False,
        "is_live": False,
        "source": "team_epg_xmltv",
    }

    missing: list[str] = []
    if dispatcharr_channel is None:
        missing.append("dispatcharr_channel")
    if not xmltv_content:
        missing.append("team_epg_xmltv")
    elif next_live_window is None:
        missing.append("next_live_window")

    status = "ready" if not missing else "incomplete"

    return {
        "team": {
            "id": team["id"],
            "provider": team["provider"],
            "provider_team_id": team["provider_team_id"],
            "primary_league": team["primary_league"],
            "leagues": team.get("leagues") or [],
            "sport": team["sport"],
            "team_name": team["team_name"],
            "team_abbrev": team.get("team_abbrev"),
            "channel_id": team["channel_id"],
            "active": bool(team.get("active")),
        },
        "dispatcharr_channel": dispatcharr_payload,
        "next_live_window": programme_payload,
        "status": status,
        "missing": missing,
        "xmltv_updated_at": xmltv_updated_at,
    }
