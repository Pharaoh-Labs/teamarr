"""Cup knockout rounds, legs and aggregates from ESPN soccer payloads (#916).

ESPN describes a two-legged tie structurally: ``competitions[0].leg`` carries
``{value, displayValue}`` on both legs, and ``competitions[0].series`` carries
``title`` ('Round of 16'), ``completed``, ``totalCompetitions`` and one
``competitors`` entry per side with ``winner`` and, once the tie is decided,
``aggregateScore``. The summary endpoint's header has the same under
``header.competitions[0]``, except ``series`` is a list there. A one-off final
and a league-phase match carry neither; the round then comes from
``season.slug`` ('final') with the stage label read off ``altGameNote``
('UEFA Champions League, Final'). The summary's ``seasonseries`` is
head-to-head history ('BAR leads series 3-0-1') and is never read.

Measured on the 2025-26 UCL/UEL (tests/providers/fixtures/
espn_uefa_knockouts_2025-26.json): aggregates are null until the second leg
is final; a tie level on aggregate and decided on penalties carries equal
aggregates with ``winner`` on the side that won the shootout; a final decided
on penalties has ``STATUS_FINAL_PEN`` and ``shootoutScore`` but no leg.
"""

from __future__ import annotations

import re
from typing import Any

# season.slug values ESPN uses for knockout stages. A two-legged tie also
# announces itself through ``series.title``, so this set only has to name the
# one-off stages a slug alone identifies.
KNOCKOUT_SLUGS = frozenset(
    {
        "knockout-round-playoffs",
        "round-of-32",
        "round-of-16",
        "quarterfinals",
        "semifinals",
        "third-place",
        "final",
    }
)

_LEG_NOTE_RE = re.compile(r"^\s*(1st|2nd)\s+leg\b", re.IGNORECASE)


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _series_dict(raw: Any) -> dict:
    """The tie's series block; the summary header wraps it in a list."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and ("totalCompetitions" in item or "leg" in item):
                return item
        return raw[0] if raw and isinstance(raw[0], dict) else {}
    return {}


def parse_knockout(
    competition: dict,
    season: dict | None,
    home_id: str | None,
    away_id: str | None,
) -> dict:
    """Return the six ``Event`` knockout fields for a soccer competition.

    Every field is empty/None unless the payload says otherwise; a league-phase
    or group match yields all-empty, which is what makes ``has_knockout_round``
    and ``{match_leg}`` safe on every other soccer game.
    """
    series = _series_dict(competition.get("series"))

    leg_raw = competition.get("leg")
    match_leg = _int(leg_raw.get("value")) if isinstance(leg_raw, dict) else None
    if match_leg is None:
        match_leg = _int(series.get("leg"))
    if match_leg is None:
        notes = competition.get("notes") or []
        headline = (notes[0].get("headline") if notes and isinstance(notes[0], dict) else "") or ""
        m = _LEG_NOTE_RE.match(headline)
        if m:
            match_leg = 1 if m.group(1).lower() == "1st" else 2

    legs_total = _int(series.get("totalCompetitions"))

    knockout_round = str(series.get("title") or "").strip()
    slug = str((season or {}).get("slug") or "").strip().lower()
    if not knockout_round and slug in KNOCKOUT_SLUGS:
        note = str(competition.get("altGameNote") or "").strip()
        if ", " in note:
            knockout_round = note.rsplit(", ", 1)[-1].strip()
        else:
            knockout_round = slug.replace("-", " ").title()

    aggregate_home = aggregate_away = None
    tie_winner = ""
    if series.get("completed") is True:
        by_id = {
            str(c.get("id")): c for c in (series.get("competitors") or []) if isinstance(c, dict)
        }
        home = by_id.get(str(home_id)) if home_id is not None else None
        away = by_id.get(str(away_id)) if away_id is not None else None
        if home and away:
            ah, aa = _int(home.get("aggregateScore")), _int(away.get("aggregateScore"))
            if ah is not None and aa is not None:
                aggregate_home, aggregate_away = ah, aa
            if home.get("winner") is True and away.get("winner") is not True:
                tie_winner = "home"
            elif away.get("winner") is True and home.get("winner") is not True:
                tie_winner = "away"

    return {
        "knockout_round": knockout_round,
        "match_leg": match_leg,
        "match_legs_total": legs_total,
        "aggregate_home": aggregate_home,
        "aggregate_away": aggregate_away,
        "tie_winner": tie_winner,
    }
