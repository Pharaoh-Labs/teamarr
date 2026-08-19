"""League configuration queries.

Single source of truth for league → provider routing.
The `leagues` table contains both API config and display data for explicitly
configured leagues (~30). Discovered leagues (~300) live in `league_cache`.

Note: LeagueMapping is defined in core.interfaces for layer separation.
This module uses it for database operations.
"""

import sqlite3

from teamarr.core import LeagueMapping


def get_league_sport(conn: sqlite3.Connection, league_code: str) -> str | None:
    """Get the sport for a league.

    Args:
        conn: Database connection
        league_code: League code (e.g., 'nfl', 'eng.1')

    Returns:
        Sport name lowercase (e.g., 'football', 'soccer') or None if not found
    """
    cursor = conn.execute(
        "SELECT sport FROM leagues WHERE league_code = ?",
        (league_code,),
    )
    row = cursor.fetchone()
    return row["sport"].lower() if row else None


def get_league(conn: sqlite3.Connection, league_code: str) -> dict | None:
    """Get league info including event_type.

    Args:
        conn: Database connection
        league_code: Canonical league code

    Returns:
        Dict with league info or None if not found
    """
    cursor = conn.execute(
        """
        SELECT league_code, provider, display_name, sport, event_type
        FROM leagues
        WHERE league_code = ? AND enabled = 1
        LIMIT 1
        """,
        (league_code.lower(),),
    )
    row = cursor.fetchone()
    if not row:
        return None
    return dict(row)


def get_leagues_bulk(conn: sqlite3.Connection, league_codes: list[str]) -> dict[str, dict]:
    """Get league info for many leagues in one query.

    Same shape as get_league per entry; missing/disabled leagues are simply
    absent from the result. Used by the matcher, whose search space can span
    hundreds of leagues (channel-source groups) — one query instead of one
    per league.
    """
    if not league_codes:
        return {}
    codes = [code.lower() for code in league_codes]
    placeholders = ",".join("?" * len(codes))
    cursor = conn.execute(
        f"""
        SELECT league_code, provider, display_name, sport, event_type
        FROM leagues
        WHERE league_code IN ({placeholders}) AND enabled = 1
        """,
        codes,
    )
    return {row["league_code"]: dict(row) for row in cursor.fetchall()}


def get_league_id(conn: sqlite3.Connection, league_code: str) -> str:
    """Get the URL-safe league ID for a league.

    Returns league_id if configured, otherwise returns league_code.
    This is the SINGLE SOURCE OF TRUTH for resolving league IDs.

    Args:
        conn: Database connection
        league_code: Raw league code (e.g., 'eng.1', 'college-football')

    Returns:
        league_id (e.g., 'epl', 'ncaaf') if configured, otherwise league_code
    """
    cursor = conn.execute(
        "SELECT league_id FROM leagues WHERE league_code = ?",
        (league_code,),
    )
    row = cursor.fetchone()
    if row and row["league_id"]:
        return row["league_id"]
    return league_code


def get_league_display(conn: sqlite3.Connection, league_code: str) -> str:
    """Get the display name for a league.

    Returns league_alias if configured, otherwise display_name, otherwise league_code.

    Args:
        conn: Database connection
        league_code: Raw league code (e.g., 'eng.1', 'college-football')

    Returns:
        Display name (e.g., 'EPL', 'NCAAF') if configured, otherwise league_code
    """
    cursor = conn.execute(
        "SELECT league_alias, display_name FROM leagues WHERE league_code = ?",
        (league_code,),
    )
    row = cursor.fetchone()
    if row:
        if row["league_alias"]:
            return row["league_alias"]
        if row["display_name"]:
            return row["display_name"]
    return league_code.upper()


def get_league_mapping(
    conn: sqlite3.Connection, league_code: str, provider: str
) -> LeagueMapping | None:
    """Get mapping for a league from a specific provider.

    Args:
        conn: Database connection
        league_code: Canonical league code (e.g., 'nfl', 'ohl')
        provider: Provider name ('espn' or 'tsdb')

    Returns:
        LeagueMapping or None if not found/disabled
    """
    cursor = conn.execute(
        """
        SELECT league_code, provider, provider_league_id,
               provider_league_name, sport, display_name, logo_url
        FROM leagues
        WHERE league_code = ? AND provider = ? AND enabled = 1
        """,
        (league_code.lower(), provider),
    )
    row = cursor.fetchone()
    if not row:
        return None

    return LeagueMapping(
        league_code=row["league_code"],
        provider=row["provider"],
        provider_league_id=row["provider_league_id"],
        provider_league_name=row["provider_league_name"],
        sport=row["sport"],
        display_name=row["display_name"],
        logo_url=row["logo_url"],
    )


def provider_supports_league(conn: sqlite3.Connection, league_code: str, provider: str) -> bool:
    """Check if a provider supports a league.

    Args:
        conn: Database connection
        league_code: Canonical league code
        provider: Provider name

    Returns:
        True if provider has enabled mapping for this league
    """
    cursor = conn.execute(
        """
        SELECT 1 FROM leagues
        WHERE league_code = ? AND provider = ? AND enabled = 1
        """,
        (league_code.lower(), provider),
    )
    return cursor.fetchone() is not None


def get_leagues_for_provider(conn: sqlite3.Connection, provider: str) -> list[LeagueMapping]:
    """Get all enabled leagues for a provider.

    Args:
        conn: Database connection
        provider: Provider name

    Returns:
        List of LeagueMapping for all enabled leagues
    """
    cursor = conn.execute(
        """
        SELECT league_code, provider, provider_league_id,
               provider_league_name, sport, display_name, logo_url
        FROM leagues
        WHERE provider = ? AND enabled = 1
        ORDER BY league_code
        """,
        (provider,),
    )
    return [
        LeagueMapping(
            league_code=row["league_code"],
            provider=row["provider"],
            provider_league_id=row["provider_league_id"],
            provider_league_name=row["provider_league_name"],
            sport=row["sport"],
            display_name=row["display_name"],
            logo_url=row["logo_url"],
        )
        for row in cursor.fetchall()
    ]


def get_all_leagues(conn: sqlite3.Connection) -> list[dict]:
    """Get all enabled leagues.

    Returns:
        List of dicts with league info including display_name
    """
    cursor = conn.execute(
        """
        SELECT league_code, provider, display_name, sport, league_alias
        FROM leagues
        WHERE enabled = 1
        ORDER BY sport, display_name
        """
    )
    return [dict(row) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# Custom-league write path (epic teamarrv2-eqz)
#
# The functions above are read-only. These add the write path the table lacked.
# They are deliberately low-level (raw row I/O); all policy — premium gate,
# TSDB-only, sport/event_type guardrails, built-in protection — lives one layer
# up in ``services/custom_leagues.py``. ``get_db()`` auto-commits on success and
# rolls back on exception, so these never commit themselves.
# ---------------------------------------------------------------------------


def get_league_row(conn: sqlite3.Connection, league_code: str) -> dict | None:
    """Return a full league row (or None), regardless of ``enabled``.

    Unlike :func:`get_league`, this returns every column — including
    ``is_custom`` and ``enabled`` — and does not filter on ``enabled``. The
    write path needs the raw row to enforce built-in protection and to detect
    code collisions against disabled built-ins.
    """
    cursor = conn.execute(
        "SELECT * FROM leagues WHERE league_code = ?",
        (league_code.lower(),),
    )
    row = cursor.fetchone()
    return dict(row) if row else None


def list_custom_leagues(conn: sqlite3.Connection) -> list[dict]:
    """Return all user-added (``is_custom=1``) leagues for the management UI.

    Only the fields the custom-league UI renders/edits, ordered by display name.
    """
    cursor = conn.execute(
        """
        SELECT league_code, provider, provider_league_id, provider_league_name,
               display_name, sport, event_type, tsdb_tier, enabled
        FROM leagues
        WHERE is_custom = 1
        ORDER BY display_name
        """
    )
    return [dict(row) for row in cursor.fetchall()]


def insert_custom_league(
    conn: sqlite3.Connection,
    *,
    league_code: str,
    provider_league_id: str,
    provider_league_name: str,
    display_name: str,
    sport: str,
    event_type: str,
    tsdb_tier: str | None = None,
) -> None:
    """Insert a new user-added (``is_custom=1``) TSDB league row.

    Always TSDB, always enabled, always importer-visible (so the user can pull
    its teams). Caller is responsible for collision/policy checks.
    """
    conn.execute(
        """
        INSERT INTO leagues (
            league_code, provider, provider_league_id, provider_league_name,
            display_name, sport, event_type, tsdb_tier,
            enabled, import_enabled, is_custom
        ) VALUES (?, 'tsdb', ?, ?, ?, ?, ?, ?, 1, 1, 1)
        """,
        (
            league_code,
            provider_league_id,
            provider_league_name,
            display_name,
            sport,
            event_type,
            tsdb_tier,
        ),
    )


def update_custom_league_row(
    conn: sqlite3.Connection,
    league_code: str,
    *,
    provider_league_id: str,
    provider_league_name: str,
    display_name: str,
    sport: str,
    event_type: str,
    tsdb_tier: str | None = None,
) -> int:
    """Update an existing custom league. Returns the number of rows changed.

    The ``is_custom = 1`` clause is a defense-in-depth guard so a built-in can
    never be mutated even if the service-layer check were bypassed.
    """
    cursor = conn.execute(
        """
        UPDATE leagues
        SET provider_league_id = ?, provider_league_name = ?, display_name = ?,
            sport = ?, event_type = ?, tsdb_tier = ?
        WHERE league_code = ? AND is_custom = 1
        """,
        (
            provider_league_id,
            provider_league_name,
            display_name,
            sport,
            event_type,
            tsdb_tier,
            league_code,
        ),
    )
    return cursor.rowcount


def delete_custom_league_row(conn: sqlite3.Connection, league_code: str) -> int:
    """Delete a custom league. Returns the number of rows deleted.

    The ``is_custom = 1`` clause ensures only user rows are ever removed.
    """
    cursor = conn.execute(
        "DELETE FROM leagues WHERE league_code = ? AND is_custom = 1",
        (league_code,),
    )
    return cursor.rowcount


def purge_league_cache_rows(conn: sqlite3.Connection, league_code: str) -> tuple[int, int]:
    """Drop a league's cached ``team_cache``/``league_cache`` rows.

    Counterpart to the create path's :meth:`CacheRefresher._save_league_teams`,
    which scopes those caches by ``(provider, league)``. Deleting a custom league
    only removes its ``leagues`` row, so without this the cached teams + league
    row linger until the next full refresh (harmless to matching, but they show
    as ghosts in team/league pickers — see bead eqz.9). Scoped by ``league_code``
    alone (not provider): a custom code is unique, so this is both sufficient and
    robust against any provider drift between create and delete.

    Returns ``(team_rows_deleted, league_rows_deleted)``.
    """
    teams = conn.execute(
        "DELETE FROM team_cache WHERE league = ?",
        (league_code,),
    ).rowcount
    leagues = conn.execute(
        "DELETE FROM league_cache WHERE league_slug = ?",
        (league_code,),
    ).rowcount
    return teams, leagues
