"""Database operations for sports subscription.

Global sports/league subscription replaces per-group league configuration.
All event groups share the same subscribed leagues and template assignments.
"""

import json
import logging
from dataclasses import dataclass, field
from sqlite3 import Connection
from types import EllipsisType

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================


@dataclass
class SportsSubscription:
    """Global sports subscription configuration (singleton, id=1)."""

    id: int = 1
    leagues: list[str] = field(default_factory=list)
    soccer_mode: str | None = None  # NULL, 'all', 'teams', 'manual'
    soccer_followed_teams: list[dict] | None = None
    updated_at: str | None = None


@dataclass
class SubscriptionLeagueConfig:
    """Per-league overrides for channel profiles and channel groups.

    Fallback chain: per-league → global default → Dispatcharr default.
    NULL fields inherit from the global default.
    """

    id: int = 0
    league_code: str = ""
    channel_profile_ids: list[int | str] | None = None
    channel_group_id: int | None = None
    channel_group_mode: str | None = None


@dataclass
class SubscriptionTemplate:
    """Global template assignment with optional sport/league filters.

    Resolution order (most specific wins):
    1. leagues match — event.league in template's leagues array
    2. sports match — event.sport in template's sports array
    3. default — template with both sports and leagues NULL
    """

    id: int
    template_id: int
    sports: list[str] | None = None  # NULL = any, or ["mma", "boxing"]
    leagues: list[str] | None = None  # NULL = any, or ["ufc", "bellator"]
    # Joined fields (for display)
    template_name: str | None = None


# =============================================================================
# HELPERS
# =============================================================================


def _row_to_subscription(row) -> SportsSubscription:
    """Convert database row to SportsSubscription."""
    leagues = []
    if row["leagues"]:
        try:
            leagues = json.loads(row["leagues"])
        except (json.JSONDecodeError, TypeError):
            pass

    soccer_followed_teams = None
    if row["soccer_followed_teams"]:
        try:
            soccer_followed_teams = json.loads(row["soccer_followed_teams"])
        except (json.JSONDecodeError, TypeError):
            pass

    return SportsSubscription(
        id=row["id"],
        leagues=leagues,
        soccer_mode=row["soccer_mode"],
        soccer_followed_teams=soccer_followed_teams,
        updated_at=row["updated_at"],
    )


def _row_to_subscription_template(row) -> SubscriptionTemplate:
    """Convert database row to SubscriptionTemplate."""
    sports = None
    if row["sports"]:
        try:
            sports = json.loads(row["sports"])
        except (json.JSONDecodeError, TypeError):
            pass

    leagues = None
    if row["leagues"]:
        try:
            leagues = json.loads(row["leagues"])
        except (json.JSONDecodeError, TypeError):
            pass

    return SubscriptionTemplate(
        id=row["id"],
        template_id=row["template_id"],
        sports=sports,
        leagues=leagues,
        template_name=row["template_name"] if "template_name" in row.keys() else None,
    )


# =============================================================================
# SPORTS SUBSCRIPTION CRUD
# =============================================================================


def get_subscription(conn: Connection) -> SportsSubscription:
    """Get the global sports subscription (singleton).

    Returns:
        SportsSubscription (always returns a valid object, creating if needed)
    """
    row = conn.execute("SELECT * FROM sports_subscription WHERE id = 1").fetchone()
    if not row:
        # Auto-create singleton if missing
        conn.execute("INSERT OR IGNORE INTO sports_subscription (id) VALUES (1)")
        conn.commit()
        row = conn.execute("SELECT * FROM sports_subscription WHERE id = 1").fetchone()
    return _row_to_subscription(row)


def get_subscribed_league_codes(conn: Connection) -> set[str]:
    """League codes the user is subscribed to (lowercased).

    Union of the global sports subscription's event-based leagues and the
    primary leagues of followed teams, so both subscription styles are covered.
    """
    codes: set[str] = set()

    sub = get_subscription(conn)
    codes.update(code.lower() for code in (sub.leagues or []) if code)

    rows = conn.execute(
        "SELECT DISTINCT primary_league FROM teams "
        "WHERE primary_league IS NOT NULL AND primary_league != ''"
    ).fetchall()
    codes.update(row[0].lower() for row in rows if row[0])

    return codes


def update_subscription(
    conn: Connection,
    leagues: list[str] | None | EllipsisType = ...,
    soccer_mode: str | None | EllipsisType = ...,
    soccer_followed_teams: list[dict] | None | EllipsisType = ...,
) -> SportsSubscription:
    """Update the global sports subscription.

    Uses ... as sentinel for "not provided" (distinct from None which clears).

    Args:
        conn: Database connection
        leagues: List of league codes (... to keep existing)
        soccer_mode: Soccer mode string (... to keep existing, None to clear)
        soccer_followed_teams: List of followed team dicts (... to keep existing)

    Returns:
        Updated SportsSubscription
    """
    updates = []
    params = []

    if leagues is not ...:
        updates.append("leagues = ?")
        params.append(json.dumps(leagues) if leagues is not None else "[]")

    if soccer_mode is not ...:
        updates.append("soccer_mode = ?")
        params.append(soccer_mode)

    if soccer_followed_teams is not ...:
        updates.append("soccer_followed_teams = ?")
        params.append(
            json.dumps(soccer_followed_teams) if soccer_followed_teams else None
        )

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        sql = f"UPDATE sports_subscription SET {', '.join(updates)} WHERE id = 1"
        conn.execute(sql, params)
        conn.commit()
        logger.info(
            "[SUBSCRIPTION] Updated sports subscription (fields: %s)",
            ", ".join(u.split(" =")[0] for u in updates[:-1]),
        )

    return get_subscription(conn)


# =============================================================================
# SUBSCRIPTION TEMPLATES CRUD
# =============================================================================


def get_subscription_templates(conn: Connection) -> list[SubscriptionTemplate]:
    """Get all global template assignments.

    Returns:
        List of SubscriptionTemplate objects ordered by specificity (leagues first)
    """
    cursor = conn.execute(
        """SELECT st.*, t.name as template_name
           FROM subscription_templates st
           LEFT JOIN templates t ON st.template_id = t.id
           ORDER BY
               CASE WHEN st.leagues IS NOT NULL THEN 0 ELSE 1 END,
               CASE WHEN st.sports IS NOT NULL THEN 0 ELSE 1 END"""
    )
    return [_row_to_subscription_template(row) for row in cursor.fetchall()]


def get_subscription_template(
    conn: Connection, assignment_id: int
) -> SubscriptionTemplate | None:
    """Get a single subscription template assignment by ID."""
    row = conn.execute(
        """SELECT st.*, t.name as template_name
           FROM subscription_templates st
           LEFT JOIN templates t ON st.template_id = t.id
           WHERE st.id = ?""",
        (assignment_id,),
    ).fetchone()
    return _row_to_subscription_template(row) if row else None


def add_subscription_template(
    conn: Connection,
    template_id: int,
    sports: list[str] | None = None,
    leagues: list[str] | None = None,
) -> int:
    """Add a global template assignment.

    Args:
        conn: Database connection
        template_id: Template ID to assign
        sports: Optional list of sports this template applies to
        leagues: Optional list of leagues this template applies to

    Returns:
        ID of the new assignment
    """
    sports_json = json.dumps(sports) if sports else None
    leagues_json = json.dumps(leagues) if leagues else None

    cursor = conn.execute(
        """INSERT INTO subscription_templates (template_id, sports, leagues)
           VALUES (?, ?, ?)""",
        (template_id, sports_json, leagues_json),
    )
    conn.commit()
    logger.debug(
        "[SUBSCRIPTION] Added template %d (sports=%s, leagues=%s)",
        template_id,
        sports,
        leagues,
    )
    new_id = cursor.lastrowid
    assert new_id is not None  # just-inserted row always has a rowid
    return new_id


def update_subscription_template(
    conn: Connection,
    assignment_id: int,
    template_id: int | None = None,
    sports: list[str] | None | EllipsisType = ...,
    leagues: list[str] | None | EllipsisType = ...,
) -> bool:
    """Update a subscription template assignment.

    Args:
        conn: Database connection
        assignment_id: ID of the assignment to update
        template_id: New template ID (if provided)
        sports: New sports filter (None to clear, ... to keep existing)
        leagues: New leagues filter (None to clear, ... to keep existing)

    Returns:
        True if updated
    """
    updates = []
    params = []

    if template_id is not None:
        updates.append("template_id = ?")
        params.append(template_id)

    if sports is not ...:
        updates.append("sports = ?")
        params.append(json.dumps(sports) if sports else None)

    if leagues is not ...:
        updates.append("leagues = ?")
        params.append(json.dumps(leagues) if leagues else None)

    if not updates:
        return False

    params.append(assignment_id)
    cursor = conn.execute(
        f"UPDATE subscription_templates SET {', '.join(updates)} WHERE id = ?",
        params,
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_subscription_template(conn: Connection, assignment_id: int) -> bool:
    """Delete a subscription template assignment.

    Returns:
        True if deleted
    """
    cursor = conn.execute(
        "DELETE FROM subscription_templates WHERE id = ?", (assignment_id,)
    )
    conn.commit()
    if cursor.rowcount > 0:
        logger.debug("[SUBSCRIPTION] Deleted template assignment %d", assignment_id)
        return True
    return False


# =============================================================================
# TEMPLATE RESOLUTION
# =============================================================================


def get_subscription_template_for_event(
    conn: Connection,
    event_sport: str,
    event_league: str,
) -> int | None:
    """Resolve the best global template for an event based on specificity.

    Resolution order (most specific wins):
    1. leagues match — event.league in template's leagues array
    2. sports match — event.sport in template's sports array
    3. default — template with both sports and leagues NULL

    Args:
        conn: Database connection
        event_sport: Event's sport code (e.g., "mma", "football")
        event_league: Event's league code (e.g., "ufc", "nfl")

    Returns:
        Template ID or None if no template configured
    """
    templates = get_subscription_templates(conn)

    if not templates:
        return None

    logger.debug(
        "[SUBSCRIPTION] Resolving template for sport=%r, league=%r, "
        "templates=%s",
        event_sport,
        event_league,
        [(t.template_id, t.sports, t.leagues) for t in templates],
    )

    event_league_lower = event_league.lower() if event_league else ""
    event_sport_lower = event_sport.lower() if event_sport else ""

    # 1. Check for league match (most specific, case-insensitive)
    for t in templates:
        if t.leagues and event_league_lower in [
            lg.lower() for lg in t.leagues
        ]:
            logger.debug(
                "[SUBSCRIPTION] Resolved template %d (league=%r match in %s)",
                t.template_id,
                event_league,
                t.leagues,
            )
            return t.template_id

    # 2. Check for sport match (case-insensitive)
    for t in templates:
        if t.sports and event_sport_lower in [
            s.lower() for s in t.sports
        ]:
            logger.debug(
                "[SUBSCRIPTION] Resolved template %d (sport=%r match in %s)",
                t.template_id,
                event_sport,
                t.sports,
            )
            return t.template_id

    # 3. Check for default (both NULL)
    for t in templates:
        if t.sports is None and t.leagues is None:
            logger.debug(
                "[SUBSCRIPTION] Resolved template %d (default)",
                t.template_id,
            )
            return t.template_id

    logger.debug(
        "[SUBSCRIPTION] No match for sport=%r, league=%r in %d templates",
        event_sport,
        event_league,
        len(templates),
    )
    return None


# =============================================================================
# SUBSCRIPTION LEAGUE CONFIG CRUD
# =============================================================================


def get_league_configs(
    conn: Connection,
) -> list[SubscriptionLeagueConfig]:
    """Get all per-league config overrides."""
    rows = conn.execute(
        "SELECT * FROM subscription_league_config ORDER BY league_code"
    ).fetchall()
    return [_build_league_config(row) for row in rows]


def get_league_config(
    conn: Connection, league_code: str
) -> SubscriptionLeagueConfig | None:
    """Get config for a specific league."""
    row = conn.execute(
        "SELECT * FROM subscription_league_config WHERE league_code = ?",
        (league_code,),
    ).fetchone()
    return _build_league_config(row) if row else None


def upsert_league_config(
    conn: Connection,
    league_code: str,
    channel_profile_ids: list[int | str] | None = None,
    channel_group_id: int | None = None,
    channel_group_mode: str | None = None,
) -> SubscriptionLeagueConfig:
    """Create or update per-league config. Returns the saved config."""
    conn.execute(
        """INSERT INTO subscription_league_config
           (league_code, channel_profile_ids, channel_group_id,
            channel_group_mode)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(league_code) DO UPDATE SET
               channel_profile_ids = excluded.channel_profile_ids,
               channel_group_id = excluded.channel_group_id,
               channel_group_mode = excluded.channel_group_mode
        """,
        (
            league_code,
            json.dumps(channel_profile_ids)
            if channel_profile_ids is not None
            else None,
            channel_group_id,
            channel_group_mode,
        ),
    )
    logger.info("[LEAGUE_CONFIG] Upserted config for %s", league_code)
    config = get_league_config(conn, league_code)
    assert config is not None  # just upserted, row must exist
    return config


def delete_league_config(conn: Connection, league_code: str) -> bool:
    """Delete per-league config. Returns True if deleted."""
    cursor = conn.execute(
        "DELETE FROM subscription_league_config WHERE league_code = ?",
        (league_code,),
    )
    if cursor.rowcount > 0:
        logger.info("[LEAGUE_CONFIG] Deleted config for %s", league_code)
        return True
    return False


def _build_league_config(row) -> SubscriptionLeagueConfig:
    """Build SubscriptionLeagueConfig from a database row."""
    profile_ids = None
    if row["channel_profile_ids"]:
        try:
            profile_ids = json.loads(row["channel_profile_ids"])
        except (json.JSONDecodeError, TypeError):
            pass
    return SubscriptionLeagueConfig(
        id=row["id"],
        league_code=row["league_code"],
        channel_profile_ids=profile_ids,
        channel_group_id=row["channel_group_id"],
        channel_group_mode=row["channel_group_mode"],
    )
