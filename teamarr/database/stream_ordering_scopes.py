"""Persistence for scoped stream-ordering rulesets.

These rulesets are stored independently from the global settings rule list.
Runtime selection is deliberately outside this module.
"""

import json
import sqlite3
from dataclasses import dataclass, field
from sqlite3 import Connection

from teamarr.database.settings.types import StreamOrderingRule


@dataclass
class StreamOrderingScope:
    """A stream-ordering ruleset assigned to sports and/or leagues."""

    id: int
    name: str
    sports: list[str] = field(default_factory=list)
    leagues: list[str] = field(default_factory=list)
    rules: list[dict] = field(default_factory=list)
    use_global_scoring: bool = True
    use_global_priority: bool = True


class ScopeAssignmentConflict(ValueError):
    """A sport or league is already assigned to another ruleset."""


def _normalize_scope_values(values: list[str]) -> list[str]:
    return sorted({value.strip().lower() for value in values if value.strip()})


def _row_to_scope(conn: Connection, row: sqlite3.Row) -> StreamOrderingScope:
    assignments = conn.execute(
        "SELECT scope_type, scope_value FROM stream_ordering_scope_assignments "
        "WHERE ruleset_id = ? ORDER BY scope_type, scope_value",
        (row["id"],),
    ).fetchall()
    return StreamOrderingScope(
        id=row["id"],
        name=row["name"],
        sports=[r["scope_value"] for r in assignments if r["scope_type"] == "sport"],
        leagues=[r["scope_value"] for r in assignments if r["scope_type"] == "league"],
        rules=json.loads(row["rules"] or "[]"),
        use_global_scoring=bool(row["use_global_scoring"]),
        use_global_priority=bool(row["use_global_priority"]),
    )


def get_stream_ordering_scopes(conn: Connection) -> list[StreamOrderingScope]:
    """Return every scoped ruleset in creation order."""
    rows = conn.execute(
        "SELECT id, name, rules, use_global_scoring, use_global_priority "
        "FROM stream_ordering_scopes ORDER BY id"
    ).fetchall()
    return [_row_to_scope(conn, row) for row in rows]


def get_stream_ordering_scope(conn: Connection, ruleset_id: int) -> StreamOrderingScope | None:
    """Return one scoped ruleset, if present."""
    row = conn.execute(
        "SELECT id, name, rules, use_global_scoring, use_global_priority "
        "FROM stream_ordering_scopes WHERE id = ?",
        (ruleset_id,),
    ).fetchone()
    return _row_to_scope(conn, row) if row else None


def _replace_assignments(
    conn: Connection, ruleset_id: int, sports: list[str], leagues: list[str]
) -> None:
    conn.execute(
        "DELETE FROM stream_ordering_scope_assignments WHERE ruleset_id = ?", (ruleset_id,)
    )
    assignments = [(ruleset_id, "sport", value) for value in _normalize_scope_values(sports)]
    assignments.extend((ruleset_id, "league", value) for value in _normalize_scope_values(leagues))
    try:
        conn.executemany(
            "INSERT INTO stream_ordering_scope_assignments (ruleset_id, scope_type, scope_value) "
            "VALUES (?, ?, ?)",
            assignments,
        )
    except sqlite3.IntegrityError as exc:
        raise ScopeAssignmentConflict(
            "Each sport or league can only be assigned to one scoped ruleset"
        ) from exc


def create_stream_ordering_scope(
    conn: Connection,
    *,
    name: str,
    sports: list[str],
    leagues: list[str],
    rules: list[dict],
    use_global_scoring: bool = True,
    use_global_priority: bool = True,
) -> StreamOrderingScope:
    """Create a scoped ruleset and its exclusive sport/league assignments."""
    cursor = conn.execute(
        "INSERT INTO stream_ordering_scopes "
        "(name, rules, use_global_scoring, use_global_priority) VALUES (?, ?, ?, ?)",
        (name.strip(), json.dumps(rules), int(use_global_scoring), int(use_global_priority)),
    )
    assert cursor.lastrowid is not None
    _replace_assignments(conn, cursor.lastrowid, sports, leagues)
    scope = get_stream_ordering_scope(conn, cursor.lastrowid)
    assert scope is not None
    return scope


def update_stream_ordering_scope(
    conn: Connection,
    ruleset_id: int,
    *,
    name: str,
    sports: list[str],
    leagues: list[str],
    rules: list[dict],
    use_global_scoring: bool = True,
    use_global_priority: bool = True,
) -> StreamOrderingScope | None:
    """Replace a scoped ruleset and its assignments."""
    cursor = conn.execute(
        "UPDATE stream_ordering_scopes SET name = ?, rules = ?, use_global_scoring = ?, "
        "use_global_priority = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (
            name.strip(),
            json.dumps(rules),
            int(use_global_scoring),
            int(use_global_priority),
            ruleset_id,
        ),
    )
    if cursor.rowcount == 0:
        return None
    _replace_assignments(conn, ruleset_id, sports, leagues)
    return get_stream_ordering_scope(conn, ruleset_id)


def delete_stream_ordering_scope(conn: Connection, ruleset_id: int) -> bool:
    """Delete a scoped ruleset and its assignments."""
    return (
        conn.execute("DELETE FROM stream_ordering_scopes WHERE id = ?", (ruleset_id,)).rowcount > 0
    )


def resolve_stream_ordering_rules(
    conn: Connection,
    sport: str | None,
    league: str | None,
) -> tuple[list[StreamOrderingRule], StreamOrderingScope | None]:
    """Return the effective rules for the most-specific matching scope.

    A matching scoped ruleset may independently inherit the scoring and priority
    families from Global. ``catch_all`` belongs to the priority family.
    """
    from teamarr.database.settings import get_stream_ordering_settings

    global_rules = get_stream_ordering_settings(conn).rules
    scopes = get_stream_ordering_scopes(conn)
    league_key = league.strip().lower() if league else ""
    sport_key = sport.strip().lower() if sport else ""
    scope = next((item for item in scopes if league_key and league_key in item.leagues), None)
    if scope is None:
        scope = next((item for item in scopes if sport_key and sport_key in item.sports), None)
    if scope is None:
        return global_rules, None

    local_rules = [StreamOrderingRule(**rule) for rule in scope.rules]
    global_scoring = [rule for rule in global_rules if rule.mode == "score"]
    global_priority = [rule for rule in global_rules if rule.mode != "score"]
    local_scoring = [rule for rule in local_rules if rule.mode == "score"]
    local_priority = [rule for rule in local_rules if rule.mode != "score"]
    return (
        (global_scoring + local_scoring if scope.use_global_scoring else local_scoring)
        + (global_priority + local_priority if scope.use_global_priority else local_priority),
        scope,
    )
