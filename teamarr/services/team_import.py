"""Team bulk import service.

Handles the business logic of importing teams from the provider cache,
including soccer league consolidation and non-soccer deduplication.
"""

import json
import logging
from dataclasses import dataclass
from sqlite3 import Connection

from teamarr.database.leagues import get_league_id

logger = logging.getLogger(__name__)


@dataclass
class ImportTeam:
    """Team data for bulk import."""

    team_name: str
    team_abbrev: str | None
    provider: str
    provider_team_id: str
    league: str
    sport: str
    logo_url: str | None


@dataclass
class ImportResult:
    """Result of a bulk import operation."""

    imported: int
    updated: int
    skipped: int


def _parse_leagues(leagues_str: str | None) -> list[str]:
    """Parse leagues JSON string to list."""
    if not leagues_str:
        return []
    try:
        return json.loads(leagues_str)
    except (json.JSONDecodeError, TypeError):
        return []


_TBD_NAMES = {"tbd", "tbd tbd"}


def _generate_channel_id(
    conn: Connection,
    team_name: str,
    primary_league: str,
    provider_team_id: str,
    used_ids: set[str],
) -> str:
    """Generate a unique channel ID from team name and league.

    If the base channel_id collides with an existing DB row or an ID already
    used in this import batch, appends the provider_team_id to disambiguate.
    """

    name = "".join(
        word.capitalize()
        for word in "".join(c if c.isalnum() or c.isspace() else "" for c in team_name).split()
    )
    league_id = get_league_id(conn, primary_league)
    base_id = f"{name}.{league_id}"

    if base_id not in used_ids:
        row = conn.execute(
            "SELECT 1 FROM teams WHERE channel_id = ?", (base_id,)
        ).fetchone()
        if not row:
            return base_id

    # Collision — disambiguate with provider team ID
    return f"{base_id}.{provider_team_id}"


def bulk_import_teams(conn: Connection, teams: list[ImportTeam]) -> ImportResult:
    """Import teams from cache with soccer consolidation.

    Key behavior:
    - Soccer: teams play in multiple competitions (EPL + Champions League), so
      they are consolidated by (provider, provider_team_id, sport). New leagues
      are added to existing team's leagues array.
    - Non-soccer: ESPN reuses team IDs across leagues for DIFFERENT teams
      (e.g., ID 8 = Detroit Pistons in NBA, Minnesota Lynx in WNBA).
      Each league gets its own team entry.

    Args:
        conn: Database connection (caller manages transaction)
        teams: List of teams to import

    Returns:
        ImportResult with counts of imported, updated, skipped
    """
    # Filter out TBD placeholder teams (ESPN data quality issue)
    original_count = len(teams)
    teams = [t for t in teams if t.team_name.strip().lower() not in _TBD_NAMES]
    if len(teams) < original_count:
        logger.info(
            "[BULK_IMPORT] Filtered %d TBD placeholder teams", original_count - len(teams)
        )

    imported = 0
    updated = 0
    skipped = 0
    used_ids: set[str] = set()  # Track channel_ids used in this batch

    # Build two indexes for existing teams:
    # 1. Full key (provider, id, sport, league) - for exact lookups
    # 2. Sport key (provider, id, sport) - for soccer consolidation lookups
    cursor = conn.execute(
        "SELECT id, provider, provider_team_id, sport, primary_league, leagues FROM teams"
    )
    existing_full: dict[tuple[str, str, str, str], tuple[int, list[str]]] = {}
    existing_sport: dict[tuple[str, str, str], list[tuple[int, str, list[str]]]] = {}

    for row in cursor.fetchall():
        full_key = (
            row["provider"],
            row["provider_team_id"],
            row["sport"],
            row["primary_league"],
        )
        sport_key = (row["provider"], row["provider_team_id"], row["sport"])
        leagues = _parse_leagues(row["leagues"])

        existing_full[full_key] = (row["id"], leagues)
        if sport_key not in existing_sport:
            existing_sport[sport_key] = []
        existing_sport[sport_key].append((row["id"], row["primary_league"], leagues))

    # Pre-load all leagues from team_cache for soccer teams (avoids N+1 queries)
    soccer_teams = [t for t in teams if t.sport.lower() == "soccer"]
    team_cache_leagues: dict[tuple[str, str, str], list[str]] = {}
    if soccer_teams:
        keys = [(t.provider, t.provider_team_id, t.sport) for t in soccer_teams]
        unique_keys = list(set(keys))
        if unique_keys:
            placeholders = " OR ".join(
                ["(provider = ? AND provider_team_id = ? AND sport = ?)"] * len(unique_keys)
            )
            params = [val for key in unique_keys for val in key]
            cursor = conn.execute(
                f"SELECT provider, provider_team_id, sport, league FROM team_cache WHERE {placeholders}",  # noqa: E501
                params,
            )
            for row in cursor.fetchall():
                cache_key = (row["provider"], row["provider_team_id"], row["sport"])
                if cache_key not in team_cache_leagues:
                    team_cache_leagues[cache_key] = []
                team_cache_leagues[cache_key].append(row["league"])

    for team in teams:
        is_soccer = team.sport.lower() == "soccer"
        full_key = (team.provider, team.provider_team_id, team.sport, team.league)
        sport_key = (team.provider, team.provider_team_id, team.sport)

        if is_soccer:
            # Soccer: consolidate all leagues into one team entry
            all_leagues = team_cache_leagues.get(sport_key, []).copy()
            if team.league not in all_leagues:
                all_leagues.append(team.league)

            if sport_key in existing_sport:
                # Found existing soccer team - update its leagues array
                team_id, primary_league, current_leagues = existing_sport[sport_key][0]
                new_to_add = [lg for lg in all_leagues if lg not in current_leagues]
                if not new_to_add:
                    skipped += 1
                else:
                    new_leagues = sorted(set(current_leagues + all_leagues))
                    conn.execute(
                        "UPDATE teams SET leagues = ? WHERE id = ?",
                        (json.dumps(new_leagues), team_id),
                    )
                    existing_sport[sport_key][0] = (team_id, primary_league, new_leagues)
                    updated += 1
            else:
                # Create new soccer team
                channel_id = _generate_channel_id(
                    conn, team.team_name, team.league, team.provider_team_id, used_ids
                )
                leagues_json = json.dumps(sorted(all_leagues))
                cursor = conn.execute(
                    """
                    INSERT INTO teams (
                        provider, provider_team_id, primary_league, leagues, sport,
                        team_name, team_abbrev, team_logo_url, channel_id, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        team.provider,
                        team.provider_team_id,
                        team.league,
                        leagues_json,
                        team.sport,
                        team.team_name,
                        team.team_abbrev,
                        team.logo_url,
                        channel_id,
                    ),
                )
                used_ids.add(channel_id)
                new_id = cursor.lastrowid
                assert new_id is not None  # INSERT always yields a rowid
                existing_full[full_key] = (new_id, all_leagues)
                existing_sport[sport_key] = [(new_id, team.league, all_leagues)]
                imported += 1
        else:
            # Non-soccer: each league gets its own team entry
            # ESPN reuses IDs across leagues for different teams
            if full_key in existing_full:
                skipped += 1
            else:
                channel_id = _generate_channel_id(
                    conn, team.team_name, team.league, team.provider_team_id, used_ids
                )
                leagues_json = json.dumps([team.league])
                cursor = conn.execute(
                    """
                    INSERT INTO teams (
                        provider, provider_team_id, primary_league, leagues, sport,
                        team_name, team_abbrev, team_logo_url, channel_id, active
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    (
                        team.provider,
                        team.provider_team_id,
                        team.league,
                        leagues_json,
                        team.sport,
                        team.team_name,
                        team.team_abbrev,
                        team.logo_url,
                        channel_id,
                    ),
                )
                used_ids.add(channel_id)
                new_id = cursor.lastrowid
                assert new_id is not None  # INSERT always yields a rowid
                existing_full[full_key] = (new_id, [team.league])
                if sport_key not in existing_sport:
                    existing_sport[sport_key] = []
                existing_sport[sport_key].append((new_id, team.league, [team.league]))
                imported += 1

    logger.info(
        "[BULK_IMPORT] Teams: %d imported, %d updated, %d skipped", imported, updated, skipped
    )
    return ImportResult(imported=imported, updated=updated, skipped=skipped)
