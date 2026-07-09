"""Tennis match parsing for ESPN provider.

ESPN tennis scoreboards return one event per TOURNAMENT (e.g. "Wimbledon"
spanning 3 weeks) with individual matches nested under
groupings[].competitions[]. Teamarr models one Event per MATCH — each match
carries its own start time, competitors (athletes, or roster pairs for
doubles), round, court assignment, and status.

Mirrors the UFC fighter-as-team pattern: players ride home_team/away_team
as Team objects, with the surname as the abbreviation (streams reference
players by surname only: "Wimbledon: Zheng vs Norrie @ Jun 29 12:30 PM").
"""

import logging
from datetime import date, datetime
from typing import TYPE_CHECKING

from teamarr.core import Event, EventStatus, Team, Venue

logger = logging.getLogger(__name__)

# Draw types (grouping slugs) each tennis league keeps. Grand slams appear
# verbatim on BOTH the atp and wta endpoints with all five groupings, so the
# split must be disjoint or subscribed atp+wta would double every slam match.
# Mixed doubles is assigned to atp (arbitrary but exclusive).
_TENNIS_LEAGUE_GROUPINGS: dict[str, frozenset[str]] = {
    "atp": frozenset({"mens-singles", "mens-doubles", "mixed-doubles"}),
    "wta": frozenset({"womens-singles", "womens-doubles"}),
}


def _tennis_surnames(name: str) -> str:
    """Surname portion of a player or doubles-pair display name.

    Streams reference players by surname only ("Zheng vs Norrie"), including
    multi-word surnames ("Alex de Minaur" → "de Minaur", "Camilo Ugo
    Carabelli" → "Ugo Carabelli"). Doubles rosters ("Hugo Nys / Edouard
    Roger-Vasselin") yield "Nys/Roger-Vasselin".
    """
    parts = []
    for person in name.split("/"):
        tokens = person.strip().split()
        parts.append(" ".join(tokens[1:]) if len(tokens) > 1 else person.strip())
    return "/".join(parts)


def _is_home(competitor: dict) -> bool:
    """True when ESPN marks this tennis competitor as the 'home' slot."""
    return (competitor.get("homeAway") or "").lower() == "home"


class TennisParserMixin:
    """Mixin providing tennis-specific parsing methods.

    Requires:
        - self.name: Provider name ('espn')
    """

    if TYPE_CHECKING:
        # Provided by the host provider class (ESPNProvider).
        name: str

    def _parse_tennis_matches(
        self, data: dict, league: str, sport: str, target_date: date
    ) -> list[Event]:
        """Parse a tennis tournament into one Event per match.

        Grand slams are duplicated verbatim across the atp AND wta endpoints
        (same event id, ALL groupings in both), so each league keeps only its
        own draw types (_TENNIS_LEAGUE_GROUPINGS) to avoid double events.

        The scoreboard is NOT date-filtered by ESPN (?dates= returns whole
        overlapping tournaments), so matches are sliced client-side to the
        requested target_date (UTC) — the service layer caches per
        (league, date) and the matcher pools a multi-day window.
        """
        tournament_id = data.get("id", "")
        tournament_name = data.get("shortName") or data.get("name", "")
        if not tournament_id or not tournament_name:
            return []

        venue_name = (data.get("venue") or {}).get("displayName", "")

        allowed = _TENNIS_LEAGUE_GROUPINGS.get(league)
        events: list[Event] = []
        for grouping in data.get("groupings", []):
            grouping_info = grouping.get("grouping") or {}
            slug = grouping_info.get("slug", "")
            if allowed is not None and slug not in allowed:
                continue
            draw_type = grouping_info.get("displayName") or slug

            for competition in grouping.get("competitions", []):
                event = self._parse_tennis_match(
                    competition,
                    league=league,
                    sport=sport,
                    tournament_id=tournament_id,
                    tournament_name=tournament_name,
                    draw_type=draw_type,
                    venue_name=venue_name,
                    target_date=target_date,
                )
                if event:
                    events.append(event)

        return events

    def _parse_tennis_match(
        self,
        competition: dict,
        *,
        league: str,
        sport: str,
        tournament_id: str,
        tournament_name: str,
        draw_type: str,
        venue_name: str,
        target_date: date,
    ) -> Event | None:
        """Parse a single tennis match (one groupings[].competitions[] entry)."""
        try:
            comp_id = competition.get("id", "")
            date_str = competition.get("date")
            if not comp_id or not date_str:
                return None

            start_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            # Client-side date slice (see _parse_tennis_matches docstring)
            if start_time.date() != target_date:
                return None

            competitors = competition.get("competitors", [])
            if len(competitors) != 2:
                return None
            competitors = sorted(competitors, key=lambda c: c.get("order") or 0)

            first = self._parse_tennis_player(competitors[0], league, sport)
            second = self._parse_tennis_player(competitors[1], league, sport)
            if first is None or second is None:
                return None

            home = first if _is_home(competitors[0]) else second
            away = second if home is first else first
            # Event name is always "away vs home" so the {player1}/{player2}
            # template variables (player1 = away) match the title ordering.
            first, second = away, home

            status_data = competition.get("status") or {}
            type_data = status_data.get("type") or {}
            state = type_data.get("state", "pre")
            if state == "in":
                status = EventStatus(state="live", detail=type_data.get("detail"))
            elif state == "post":
                status = EventStatus(state="final", detail=type_data.get("detail"))
            else:
                status = EventStatus(state="scheduled")

            venue_data = competition.get("venue") or {}
            court = (venue_data.get("court") or "").strip() or None
            full_venue = venue_data.get("fullName") or venue_name

            broadcasts: list[str] = []
            for broadcast in competition.get("broadcasts") or []:
                for bname in broadcast.get("names") or []:
                    if bname and bname not in broadcasts:
                        broadcasts.append(bname)

            round_data = competition.get("round") or {}
            round_name = (
                round_data.get("displayName") if isinstance(round_data, dict) else None
            )

            # Final-match result line, e.g. "Piros (HUN) bt Ivanov (BUL) 6-2 6-2"
            game_recap = ""
            if state == "post":
                notes = competition.get("notes") or []
                if notes and isinstance(notes[0], dict):
                    game_recap = notes[0].get("text") or ""

            return Event(
                id=f"{tournament_id}-{comp_id}",
                provider=self.name,
                name=f"{tournament_name}: {first.name} vs {second.name}",
                short_name=f"{first.short_name} vs {second.short_name}",
                start_time=start_time,
                home_team=home,
                away_team=away,
                status=status,
                league=league,
                sport=sport,
                venue=Venue(name=full_venue) if full_venue else None,
                broadcasts=broadcasts,
                game_recap=game_recap,
                tournament_name=tournament_name,
                round_name=round_name,
                court=court,
                draw_type=draw_type,
            )
        except Exception as e:
            logger.warning("[ESPN_TENNIS] Failed to parse match: %s", e)
            return None

    def _parse_tennis_player(
        self, competitor: dict, league: str, sport: str
    ) -> Team | None:
        """Convert a tennis competitor (athlete or doubles roster) to a Team.

        ESPN scoreboard athlete ids are null, so the id is a name-derived
        slug — matching is name-based, never id-based.
        """
        athlete = competitor.get("athlete") or {}
        roster = competitor.get("roster") or {}
        name = athlete.get("displayName") or roster.get("displayName")
        if not name:
            return None

        short_name = athlete.get("shortName") or name
        surname = _tennis_surnames(name)

        slug = "".join(ch for ch in name.lower() if ch.isalnum() or ch == " ")
        return Team(
            id=f"player_{slug.replace(' ', '_')}",
            provider=self.name,
            name=name,
            short_name=short_name,
            abbreviation=surname,
            league=league,
            sport=sport,
            logo_url=None,
            color=None,
        )
