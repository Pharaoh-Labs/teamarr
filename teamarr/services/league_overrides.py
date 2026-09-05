"""User overrides for built-in league display fields (#371, #355 item 13).

The leagues seed replaces whole rows (INSERT OR REPLACE) on every startup,
so user edits made directly to the leagues table are wiped (the #194
lesson). Overrides live in the league_overrides table instead and win over
curated values at read time (LeagueMappingService fallback chain, step 0).

Writes reload the in-memory league mapping cache so the change takes effect
without a restart.
"""

import logging

from teamarr.database import get_db
from teamarr.services.league_mappings import get_league_mapping_service

logger = logging.getLogger(__name__)


class LeagueNotFoundError(ValueError):
    """The league_code doesn't exist in the leagues table."""


def list_gracenote_overrides() -> list[dict]:
    """All current gracenote_category overrides, with their defaults."""
    service = get_league_mapping_service()
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT league_code, gracenote_category
            FROM league_overrides
            WHERE gracenote_category IS NOT NULL
            ORDER BY league_code
            """
        ).fetchall()
    return [
        {
            "league_code": row["league_code"],
            "gracenote_category": row["gracenote_category"],
            "default": service.get_default_gracenote_category(row["league_code"]),
        }
        for row in rows
    ]


def get_gracenote_override_state(league_code: str) -> dict:
    """Override/default/effective category for one league."""
    _require_league(league_code)
    service = get_league_mapping_service()
    with get_db() as conn:
        row = conn.execute(
            "SELECT gracenote_category FROM league_overrides WHERE league_code = ?",
            (league_code,),
        ).fetchone()
    override = row["gracenote_category"] if row else None
    return {
        "league_code": league_code,
        "override": override,
        "default": service.get_default_gracenote_category(league_code),
        "effective": service.get_gracenote_category(league_code),
    }


def set_gracenote_override(league_code: str, value: str | None) -> dict:
    """Upsert (or clear, when value is empty/None) the category override.

    Reloads the league mapping cache so templates pick the change up
    immediately. Returns the new state (see get_gracenote_override_state).
    """
    _require_league(league_code)
    value = (value or "").strip() or None
    with get_db() as conn:
        if value is None:
            conn.execute(
                "DELETE FROM league_overrides WHERE league_code = ?", (league_code,)
            )
        else:
            conn.execute(
                """
                INSERT INTO league_overrides (league_code, gracenote_category, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(league_code) DO UPDATE SET
                    gracenote_category = excluded.gracenote_category,
                    updated_at = excluded.updated_at
                """,
                (league_code, value),
            )
        conn.commit()
    get_league_mapping_service().reload()
    logger.info(
        "[LEAGUE_OVERRIDES] gracenote_category for %s %s",
        league_code,
        f"set to {value!r}" if value else "cleared",
    )
    return get_gracenote_override_state(league_code)


def _require_league(league_code: str) -> None:
    """Accept any league the league picker can offer (#709).

    The picker lists the UNION of configured leagues and discovered ones
    (``league_cache``), so gating on the ``leagues`` table alone rejected
    every discovered league — e.g. ``eng.5`` (English National League) —
    with "Unknown league". The override read path already resolves those:
    ``get_default_gracenote_category`` falls back to the league_cache name
    and sport, so an override on a discovered league renders correctly.
    """
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT 1 FROM leagues WHERE league_code = ?
            UNION ALL
            SELECT 1 FROM league_cache WHERE league_slug = ?
            LIMIT 1
            """,
            (league_code, league_code),
        ).fetchone()
    if row is None:
        raise LeagueNotFoundError(f"Unknown league: {league_code}")
