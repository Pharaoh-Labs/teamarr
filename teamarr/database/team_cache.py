"""Team cache database queries.

Simple queries for the team_cache table.
Used by providers to look up team names without going through consumers layer.
"""

from sqlite3 import Connection

from teamarr.core.sports import get_sport_display_names_from_db


def get_team_name_by_id(
    conn: Connection,
    provider_team_id: str,
    league: str,
    provider: str = "tsdb",
) -> str | None:
    """Get team name from provider team ID.

    Uses seeded/cached data instead of making API calls.
    This is critical for TSDB performance - avoids 2 API calls per lookup.

    Args:
        conn: Database connection
        provider_team_id: Team ID from the provider
        league: League slug to search in
        provider: Provider name (default 'tsdb')

    Returns:
        Team name if found, None otherwise
    """
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT team_name FROM team_cache
        WHERE provider_team_id = ? AND league = ? AND provider = ?
        """,
        (provider_team_id, league, provider),
    )
    row = cursor.fetchone()
    return row["team_name"] if row else None


def get_team_identity(
    conn: Connection,
    provider: str,
    provider_team_id: str,
    league: str,
) -> dict | None:
    """Look up canonical team identity from the cache.

    Returns the team_name / team_abbrev / team_short_name fields seeded by the
    cache refresh, which pull from each provider's `/teams` endpoint (where
    short_name and abbreviation are reliably populated). Used by the service
    layer to backfill events whose teams came from a degraded endpoint
    (e.g. ESPN's summary endpoint, which omits shortDisplayName).
    """
    cursor = conn.execute(
        """
        SELECT team_name, team_abbrev, team_short_name, logo_url
        FROM team_cache
        WHERE provider = ? AND provider_team_id = ? AND league = ?
        """,
        (provider, provider_team_id, league),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return {
        "name": row["team_name"],
        "abbreviation": row["team_abbrev"],
        "short_name": row["team_short_name"],
        "logo_url": row["logo_url"],
    }


def get_team_leagues_from_cache(
    conn: Connection,
    provider: str,
    provider_team_id: str,
    sport: str,
) -> list[str]:
    """Get all leagues a team appears in from the cache for a given sport.

    Args:
        conn: Database connection
        provider: Provider name (e.g., 'espn')
        provider_team_id: Provider's team ID
        sport: Sport name

    Returns:
        List of distinct league codes
    """
    cursor = conn.execute(
        "SELECT DISTINCT league FROM team_cache WHERE provider = ? AND provider_team_id = ? AND sport = ?",  # noqa: E501
        (provider, provider_team_id, sport),
    )
    return [row["league"] for row in cursor.fetchall()]


def search_teams(
    conn: Connection,
    query: str,
    league: str | None = None,
    sport: str | None = None,
    limit: int = 50,
) -> list[dict]:
    """Search for teams in the cache by name.

    Matches against team_name (LIKE), team_abbrev (exact), and
    team_short_name (LIKE).

    Args:
        conn: Database connection
        query: Search query (case-insensitive)
        league: Optional league filter
        sport: Optional sport filter
        limit: Max results (default 50)

    Returns:
        List of matching team dicts
    """
    q_lower = query.lower().strip()

    sql = """
        SELECT team_name, team_abbrev, team_short_name, provider,
               provider_team_id, league, sport, logo_url
        FROM team_cache
        WHERE (LOWER(team_name) LIKE ?
               OR LOWER(team_abbrev) = ?
               OR LOWER(team_short_name) LIKE ?)
    """
    params: list = [f"%{q_lower}%", q_lower, f"%{q_lower}%"]

    if league:
        sql += " AND league = ?"
        params.append(league)
    if sport:
        sql += " AND sport = ?"
        params.append(sport)

    sql += " ORDER BY team_name LIMIT ?"
    params.append(limit)

    rows = conn.execute(sql, params).fetchall()
    return [
        {
            "name": row["team_name"],
            "abbrev": row["team_abbrev"],
            "short_name": row["team_short_name"],
            "provider": row["provider"],
            "team_id": row["provider_team_id"],
            "league": row["league"],
            "sport": row["sport"],
            "logo_url": row["logo_url"],
        }
        for row in rows
    ]


def list_sports(conn: Connection) -> dict[str, str]:
    """Get all sport codes and their display names.

    Args:
        conn: Database connection

    Returns:
        Dict mapping sport codes to display names
    """
    cursor = conn.execute("SELECT sport_code, display_name FROM sports ORDER BY display_name")
    return {row["sport_code"]: row["display_name"] for row in cursor.fetchall()}


def get_league_teams(conn: Connection, league_slug: str) -> list[dict]:
    """Get all teams for a specific league from the cache.

    Args:
        conn: Database connection
        league_slug: League identifier (e.g., 'nfl', 'eng.1')

    Returns:
        List of team dicts
    """
    cursor = conn.execute(
        """
        SELECT id, team_name, team_abbrev, team_short_name, provider,
               provider_team_id, league, sport, logo_url
        FROM team_cache
        WHERE league = ?
        ORDER BY team_name
        """,
        (league_slug,),
    )
    return [
        {
            "id": row["id"],
            "team_name": row["team_name"],
            "team_abbrev": row["team_abbrev"],
            "team_short_name": row["team_short_name"],
            "provider": row["provider"],
            "provider_team_id": row["provider_team_id"],
            "league": row["league"],
            "sport": row["sport"],
            "logo_url": row["logo_url"],
        }
        for row in cursor.fetchall()
    ]


def get_team_leagues(conn: Connection, provider: str, provider_team_id: str) -> list[str]:
    """Get all leagues a team plays in (distinct league slugs).

    Args:
        conn: Database connection
        provider: Provider name ('espn' or 'tsdb')
        provider_team_id: Team ID from the provider

    Returns:
        List of distinct league slugs
    """
    cursor = conn.execute(
        """
        SELECT DISTINCT league
        FROM team_cache
        WHERE provider = ? AND provider_team_id = ?
        """,
        (provider, provider_team_id),
    )
    return [row["league"] for row in cursor.fetchall()]


def get_team_picker_leagues(conn: Connection) -> list[dict]:
    """Get all leagues from team_cache for the TeamPicker component.

    Returns unique leagues from team_cache with their sports.
    Leagues that exist in the configured leagues table sort first.

    Args:
        conn: Database connection

    Returns:
        List of league dicts with sport, provider, team_count, is_configured, name, logo_url
    """

    sport_display_names = get_sport_display_names_from_db(conn)

    cursor = conn.execute(
        """
        SELECT
            tc.league,
            tc.sport,
            tc.provider,
            COUNT(*) as team_count,
            CASE WHEN l.league_code IS NOT NULL THEN 1 ELSE 0 END as is_configured,
            COALESCE(l.display_name, lc.league_name, UPPER(tc.league)) as display_name,
            l.logo_url as configured_logo_url,
            lc.logo_url as cached_logo_url
        FROM team_cache tc
        LEFT JOIN leagues l ON l.league_code = tc.league
        LEFT JOIN league_cache lc ON lc.league_slug = tc.league
        GROUP BY tc.league, tc.sport, tc.provider
        ORDER BY
            is_configured DESC,
            tc.sport,
            display_name
        """
    )

    return [
        {
            "slug": row["league"],
            "sport": row["sport"],
            "sport_display_name": sport_display_names.get(row["sport"], row["sport"].title()),
            "provider": row["provider"],
            "team_count": row["team_count"],
            "is_configured": bool(row["is_configured"]),
            "name": row["display_name"],
            "logo_url": row["configured_logo_url"] or row["cached_logo_url"],
        }
        for row in cursor.fetchall()
    ]


def get_league_info(conn: Connection, league_slug: str) -> dict | None:
    """Get info for a specific league from team_cache.

    Args:
        conn: Database connection
        league_slug: League identifier (e.g., 'nfl', 'eng.1')

    Returns:
        League info dict or None if not found
    """
    row = conn.execute(
        """
        SELECT league, provider, sport, COUNT(*) as team_count
        FROM team_cache
        WHERE league = ?
        GROUP BY league, provider, sport
        """,
        (league_slug,),
    ).fetchone()

    if not row:
        return None

    # Get league name from league_cache if available
    league_name = league_slug.upper()
    name_row = conn.execute(
        "SELECT league_name FROM league_cache WHERE league_slug = ?",
        (league_slug,),
    ).fetchone()
    if name_row:
        league_name = name_row["league_name"]

    return {
        "slug": row["league"],
        "provider": row["provider"],
        "name": league_name,
        "sport": row["sport"],
        "team_count": row["team_count"],
    }
