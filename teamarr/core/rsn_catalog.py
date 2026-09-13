"""Pre-seeded catalog of Regional Sports Networks (RSNs) and team affiliations.

Follows the zero-guessing principle:
- 1:1 unambiguous RSNs (e.g., YES Network -> NYY, NESN -> BOS, SNY -> NYM)
  resolve to the affiliated team.
- Multi-team networks (e.g., MASN covering both Orioles and Nationals) are
  flagged as ambiguous and will NEVER auto-resolve without explicit context
  (like EPG program title) or user manual mapping.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from unidecode import unidecode


@dataclass(frozen=True)
class RSNEntry:
    """RSN definition with team affiliation and match patterns."""

    network_name: str
    league: str
    team_abbreviation: str  # Primary team abbreviation (e.g., "NYY")
    patterns: tuple[str, ...]  # Regex patterns or token phrases
    is_ambiguous: bool = False  # If True, never auto-resolve without explicit user mapping
    team_synonyms: tuple[str, ...] = ()  # Alternate team abbreviations/names (e.g., "WAS", "WSH")


# Pre-seeded MLB RSN Catalog
# Covers all 30 MLB clubs and their regional broadcast homes
MLB_RSN_CATALOG: tuple[RSNEntry, ...] = (
    # --- AL East ---
    RSNEntry(
        network_name="YES Network",
        league="mlb",
        team_abbreviation="NYY",
        patterns=(r"\byes\b", r"\byes\s*network\b", r"\byes\s*hd\b"),
        team_synonyms=("NYY", "YANKEES", "NEW YORK YANKEES"),
    ),
    RSNEntry(
        network_name="NESN",
        league="mlb",
        team_abbreviation="BOS",
        patterns=(
            r"\bnesn\b",
            r"\bnesn\s*\+\b",
            r"\bnesn\s*plus\b",
            r"\bnesn\s*hd\b",
            r"\bnesn\s*national\b",
        ),
        team_synonyms=("BOS", "RED SOX", "BOSTON RED SOX"),
    ),
    RSNEntry(
        network_name="Sportsnet Canada (Blue Jays)",
        league="mlb",
        team_abbreviation="TOR",
        patterns=(
            r"\bsportsnet\s*(?:east|ontario|west|pacific|one|360)\b",
            r"\bsn\s*(?:east|ontario|west|pacific|one|360)\b",
            r"\bsn1\b",
            r"\bsn360\b",
            r"\bsportsnet\s*feed\b",
        ),
        team_synonyms=("TOR", "BLUE JAYS", "TORONTO BLUE JAYS"),
    ),
    RSNEntry(
        network_name="FanDuel Sports Network Sun",
        league="mlb",
        team_abbreviation="TB",
        patterns=(
            r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?sun\b",
            r"\bsun\s*sports\b",
        ),
        team_synonyms=("TB", "TBR", "RAYS", "TAMPA BAY RAYS"),
    ),
    # --- AL Central ---
    RSNEntry(
        network_name="Chicago Sports Network",
        league="mlb",
        team_abbreviation="CWS",
        patterns=(r"\bchsn\b", r"\bchicago\s*sports\s*network\b", r"\bchsn\s*\+\b"),
        team_synonyms=("CWS", "CHW", "WHITE SOX", "CHICAGO WHITE SOX"),
    ),
    RSNEntry(
        network_name="FanDuel Sports Network Detroit",
        league="mlb",
        team_abbreviation="DET",
        patterns=(r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?detroit\b",),
        team_synonyms=("DET", "TIGERS", "DETROIT TIGERS"),
    ),
    RSNEntry(
        network_name="FanDuel Sports Network Great Lakes / Guardians",
        league="mlb",
        team_abbreviation="CLE",
        patterns=(
            r"\bguardians\.tv\b",
            r"\bcleveland\s*guardians\s*tv\b",
            r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?great\s*lakes\b",
        ),
        team_synonyms=("CLE", "GUARDIANS", "CLEVELAND GUARDIANS"),
    ),
    RSNEntry(
        network_name="FanDuel Sports Network Kansas City",
        league="mlb",
        team_abbreviation="KC",
        patterns=(
            r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?kansas\s*city\b",
            r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?kc\b",
        ),
        team_synonyms=("KC", "KCR", "ROYALS", "KANSAS CITY ROYALS"),
    ),
    RSNEntry(
        network_name="Twins.TV / FanDuel Sports Network North",
        league="mlb",
        team_abbreviation="MIN",
        patterns=(
            r"\btwins\.tv\b",
            r"\bminnesota\s*twins\s*tv\b",
            r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?north\b",
        ),
        team_synonyms=("MIN", "TWINS", "MINNESOTA TWINS"),
    ),
    # --- AL West ---
    RSNEntry(
        network_name="Space City Home Network",
        league="mlb",
        team_abbreviation="HOU",
        patterns=(
            r"\bspace\s*city\b",
            r"\bspace\s*city\s*home\s*network\b",
            r"\bschn\b",
            r"\batt\s*sportsnet\s*southwest\b",
        ),
        team_synonyms=("HOU", "ASTROS", "HOUSTON ASTROS"),
    ),
    RSNEntry(
        network_name="FanDuel Sports Network Southwest / Rangers",
        league="mlb",
        team_abbreviation="TEX",
        patterns=(
            r"\brangers\.tv\b",
            r"\btexas\s*rangers\s*tv\b",
            r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?southwest\b",
        ),
        team_synonyms=("TEX", "RANGERS", "TEXAS RANGERS"),
    ),
    RSNEntry(
        network_name="ROOT Sports Northwest",
        league="mlb",
        team_abbreviation="SEA",
        patterns=(
            r"\broot\s*sports\b",
            r"\broot\s*sports\s*nw\b",
            r"\broot\s*sports\s*northwest\b",
            r"\brsnw\b",
        ),
        team_synonyms=("SEA", "MARINERS", "SEATTLE MARINERS"),
    ),
    RSNEntry(
        network_name="FanDuel Sports Network West (Angels)",
        league="mlb",
        team_abbreviation="LAA",
        patterns=(
            r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?west\b",
            r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?socal\b",
        ),
        team_synonyms=("LAA", "ANGELS", "LOS ANGELES ANGELS"),
    ),
    # --- NL East ---
    RSNEntry(
        network_name="SportsNet New York",
        league="mlb",
        team_abbreviation="NYM",
        patterns=(r"\bsny\b", r"\bsportsnet\s*new\s*york\b", r"\bsportsnet\s*ny\b"),
        team_synonyms=("NYM", "METS", "NEW YORK METS"),
    ),
    RSNEntry(
        network_name="NBC Sports Philadelphia",
        league="mlb",
        team_abbreviation="PHI",
        patterns=(
            r"\bnbc\s*(?:sports\s*)?(?:network\s*)?philadelphia\b",
            r"\bnbc\s*(?:sports\s*)?(?:network\s*)?philly\b",
            r"\bnbcs\s*philly\b",
            r"\bnbcs\s*philadelphia\b",
        ),
        team_synonyms=("PHI", "PHILLIES", "PHILADELPHIA PHILLIES"),
    ),
    RSNEntry(
        network_name="FanDuel Sports Network South / Southeast (Braves)",
        league="mlb",
        team_abbreviation="ATL",
        patterns=(
            r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?south\b",
            r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?southeast\b",
        ),
        team_synonyms=("ATL", "BRAVES", "ATLANTA BRAVES"),
    ),
    RSNEntry(
        network_name="FanDuel Sports Network Florida (Marlins)",
        league="mlb",
        team_abbreviation="MIA",
        patterns=(r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?florida\b",),
        team_synonyms=("MIA", "MARLINS", "MIAMI MARLINS"),
    ),
    # --- NL Central ---
    RSNEntry(
        network_name="Marquee Sports Network",
        league="mlb",
        team_abbreviation="CHC",
        patterns=(r"\bmarquee\b", r"\bmarquee\s*sports\s*network\b", r"\bmsn\s*chicago\b"),
        team_synonyms=("CHC", "CUBS", "CHICAGO CUBS"),
    ),
    RSNEntry(
        network_name="FanDuel Sports Network Midwest (Cardinals)",
        league="mlb",
        team_abbreviation="STL",
        patterns=(r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?midwest\b",),
        team_synonyms=("STL", "CARDINALS", "ST. LOUIS CARDINALS", "ST LOUIS CARDINALS"),
    ),
    RSNEntry(
        network_name="FanDuel Sports Network Wisconsin / Brewers.TV",
        league="mlb",
        team_abbreviation="MIL",
        patterns=(
            r"\bbrewers\.tv\b",
            r"\bmilwaukee\s*brewers\s*tv\b",
            r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?wisconsin\b",
            r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?wi\b",
        ),
        team_synonyms=("MIL", "BREWERS", "MILWAUKEE BREWERS"),
    ),
    RSNEntry(
        network_name="FanDuel Sports Network Ohio / Reds.TV",
        league="mlb",
        team_abbreviation="CIN",
        patterns=(
            r"\breds\.tv\b",
            r"\bcincinnati\s*reds\s*tv\b",
            r"\b(?:bally|fanduel|fdsn|bs)\s*(?:sports\s*)?(?:network\s*)?ohio\b",
        ),
        team_synonyms=("CIN", "REDS", "CINCINNATI REDS"),
    ),
    RSNEntry(
        network_name="SportsNet Pittsburgh",
        league="mlb",
        team_abbreviation="PIT",
        patterns=(
            r"\bsportsnet\s*pittsburgh\b",
            r"\bsnp\b",
            r"\batt\s*sportsnet\s*pittsburgh\b",
        ),
        team_synonyms=("PIT", "PIRATES", "PITTSBURGH PIRATES"),
    ),
    # --- NL West ---
    RSNEntry(
        network_name="Spectrum SportsNet LA",
        league="mlb",
        team_abbreviation="LAD",
        patterns=(
            r"\bsportsnet\s*la\b",
            r"\bspectrum\s*sportsnet\s*la\b",
            r"\bsnla\b",
        ),
        team_synonyms=("LAD", "DODGERS", "LOS ANGELES DODGERS"),
    ),
    RSNEntry(
        network_name="Padres.TV",
        league="mlb",
        team_abbreviation="SD",
        patterns=(
            r"\bpadres\.tv\b",
            r"\bsan\s*diego\s*padres\s*tv\b",
            r"\bpadres\s*tv\b",
        ),
        team_synonyms=("SD", "SDP", "PADRES", "SAN DIEGO PADRES"),
    ),
    RSNEntry(
        network_name="DBacks.TV",
        league="mlb",
        team_abbreviation="ARI",
        patterns=(
            r"\bdbacks\.tv\b",
            r"\bd-backs\.tv\b",
            r"\barizona\s*diamondbacks\s*tv\b",
            r"\bdiamondbacks\s*tv\b",
            r"\bdbacks\s*tv\b",
        ),
        team_synonyms=("ARI", "AZ", "DIAMONDBACKS", "D-BACKS", "ARIZONA DIAMONDBACKS"),
    ),
    RSNEntry(
        network_name="Rockies.TV",
        league="mlb",
        team_abbreviation="COL",
        patterns=(
            r"\brockies\.tv\b",
            r"\bcolorado\s*rockies\s*tv\b",
            r"\brockies\s*tv\b",
            r"\batt\s*sportsnet\s*rocky\s*mountain\b",
        ),
        team_synonyms=("COL", "ROCKIES", "COLORADO ROCKIES"),
    ),
    RSNEntry(
        network_name="NBC Sports Bay Area",
        league="mlb",
        team_abbreviation="SF",
        patterns=(
            r"\bnbc\s*(?:sports\s*)?(?:network\s*)?bay\s*area\b",
            r"\bnbcs\s*bay\s*area\b",
        ),
        team_synonyms=("SF", "SFG", "GIANTS", "SAN FRANCISCO GIANTS"),
    ),
    # --- Ambiguous Multi-Team Networks ---
    # These MUST NOT auto-resolve without user mapping or EPG data
    RSNEntry(
        network_name="Mid-Atlantic Sports Network (MASN)",
        league="mlb",
        team_abbreviation="BAL",
        patterns=(r"\bmasn\b", r"\bmasn\s*hd\b", r"\bmasn\s*1\b"),
        is_ambiguous=True,  # Shared between Orioles and Nationals
        team_synonyms=("BAL", "ORIOLES", "WSH", "WAS", "NATIONALS"),
    ),
    RSNEntry(
        network_name="MASN 2",
        league="mlb",
        team_abbreviation="WSH",
        patterns=(r"\bmasn\s*2\b", r"\bmasn2\b", r"\bmasn2\s*hd\b"),
        is_ambiguous=True,  # Shared overflow between Orioles and Nationals
        team_synonyms=("WSH", "WAS", "NATIONALS", "BAL", "ORIOLES"),
    ),
    RSNEntry(
        network_name="NBC Sports California",
        league="mlb",
        team_abbreviation="OAK",
        patterns=(
            r"\bnbc\s*(?:sports\s*)?(?:network\s*)?california\b",
            r"\bnbcs\s*california\b",
        ),
        is_ambiguous=True,  # Multi-sport / relocation ambiguity
        team_synonyms=("OAK", "ATHLETICS", "OAKLAND ATHLETICS"),
    ),
)


# Compiled pattern cache
_COMPILED_CATALOG: list[tuple[RSNEntry, list[re.Pattern]]] = [
    (entry, [re.compile(p, re.IGNORECASE) for p in entry.patterns]) for entry in MLB_RSN_CATALOG
]


def resolve_unambiguous_rsn_team(stream_text: str, league: str = "mlb") -> str | None:
    """Match stream text against the RSN catalog and return the team abbreviation.

    Returns the team abbreviation (e.g. 'NYY', 'BOS') ONLY if the stream text
    matches an unambiguous 1:1 RSN for the requested league.
    Returns None if:
    - No RSN matches.
    - An ambiguous RSN matches (e.g., MASN).
    - Multiple conflicting RSNs match.
    """
    if not stream_text:
        return None

    norm_text = unidecode(stream_text).lower().strip()
    matched_teams: set[str] = set()

    for entry, patterns in _COMPILED_CATALOG:
        if entry.league.lower() != league.lower():
            continue

        for pat in patterns:
            if pat.search(stream_text) or pat.search(norm_text):
                if entry.is_ambiguous:
                    # Ambiguous network found -> zero assumptions, refuse to auto-resolve
                    return None
                matched_teams.add(entry.team_abbreviation)
                break

    if len(matched_teams) == 1:
        return next(iter(matched_teams))

    # Zero or conflicting multiple matches -> return None
    return None


def team_matches_rsn(team: Any, target_abbreviation: str) -> bool:
    """Check if a Team object matches a target team abbreviation or known synonyms."""
    if not team or not target_abbreviation:
        return False

    target_upper = target_abbreviation.upper()

    # Direct abbreviation check
    team_abbrev = (getattr(team, "abbreviation", None) or "").upper()
    if team_abbrev and (team_abbrev == target_upper or target_upper.startswith(team_abbrev)):
        return True

    # Find entry in catalog to check team synonyms
    for entry, _ in _COMPILED_CATALOG:
        if entry.team_abbreviation.upper() == target_upper:
            # Check team name, short name, and abbreviation against synonyms
            synonyms = {s.upper() for s in entry.team_synonyms}
            synonyms.add(entry.team_abbreviation.upper())

            if team_abbrev and team_abbrev in synonyms:
                return True

            team_name = (getattr(team, "name", None) or "").upper()
            if team_name and any(s in team_name or team_name in s for s in synonyms):
                return True

            team_short = (getattr(team, "short_name", None) or "").upper()
            if team_short and any(s in team_short or team_short in s for s in synonyms):
                return True

    return False
