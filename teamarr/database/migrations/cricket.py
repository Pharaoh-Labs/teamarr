"""Offline, identity-preserving TSDB → ESPN franchise cricket migration (#1069)."""

import json
import logging
import re
import sqlite3

logger = logging.getLogger(__name__)

# Captured from ESPN's complete season scoreboard teams[] (2026-10-14).
# Names are migration keys only, never fuzzy matching rules. Old provider IDs
# are learned from persisted rows before their caches are invalidated.
CRICKET_TEAMS = {
    "mlc": {
        "Los Angeles Knight Riders": "1381354",
        "MI New York": "1381355",
        "San Francisco Unicorns": "1381357",
        "Seattle Orcas": "1381359",
        "Texas Super Kings": "1381353",
        "Washington Freedom": "1381360",
    },
    "ipl": {
        "Chennai Super Kings": "335974",
        "Delhi Capitals": "335975",
        "Gujarat Titans": "1298769",
        "Kolkata Knight Riders": "335971",
        "Lucknow Super Giants": "1298768",
        "Mumbai Indians": "335978",
        "Punjab Kings": "335973",
        "Rajasthan Royals": "335977",
        "Royal Challengers Bengaluru": "335970",
        "Sunrisers Hyderabad": "628333",
        "Royal Challengers Bangalore": "335970",
        "Kings XI Punjab": "335973",
        "Delhi Daredevils": "335975",
    },
    "bbl": {
        "Adelaide Strikers": "509667",
        "Brisbane Heat": "509668",
        "Hobart Hurricanes": "509669",
        "Melbourne Renegades": "509671",
        "Melbourne Stars": "509672",
        "Perth Scorchers": "509670",
        "Sydney Sixers": "509673",
        "Sydney Thunder": "509674",
    },
    "sa20": {
        "Durban's Super Giants": "1335272",
        "Durban Super Giants": "1335272",
        "Joburg Super Kings": "1335270",
        "MI Cape Town": "1328786",
        "Paarl Royals": "1335274",
        "Pretoria Capitals": "1335271",
        "Sunrisers Eastern Cape": "1335273",
    },
}


def _name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower()) if isinstance(value, str) else ""


def migrate_franchise_cricket(conn: sqlite3.Connection) -> None:
    """Keep local row/channel IDs and user configuration; replace provider identities.

    No network access in a migration. Unknown names/IDs are preserved and warned
    about, never deleted or turned into an unrestricted team filter. Existing
    managed event channels retain their ownership and original event identity
    until normal lifecycle retirement; marking them deleted here would orphan
    their still-live Dispatcharr channels. Durable team channels keep their FK.
    """
    names = {
        league: {_name(n): i for n, i in teams.items()} for league, teams in CRICKET_TEAMS.items()
    }
    old_ids: dict[tuple[str, str], str] = {}
    conflicts: set[tuple[str, str]] = set()

    def remember(league, old_id, new_id):
        key = (league, str(old_id))
        if key in conflicts:
            return
        if key in old_ids and old_ids[key] != new_id:
            conflicts.add(key)
            old_ids.pop(key)
            logger.warning(
                "[MIGRATE] Cricket: conflicting %s identity; preserved for review", league
            )
        else:
            old_ids[key] = new_id

    def columns(table):
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}

    # Gather every available old identity before clearing caches. This also lets
    # ID-only selections migrate when their display name lives in another table.
    sources = (
        ("team_cache", "league", "provider_team_id"),
        ("teams", "primary_league", "provider_team_id"),
        ("channel_priority_teams", "league", "provider_team_id"),
        ("team_aliases", "league", "team_id"),
        ("numbering_exceptions", "league_code", "provider_team_id"),
    )
    rows_by_table = {}
    for table, league_col, id_col in sources:
        if not {"provider", "team_name", league_col, id_col} <= columns(table):
            continue
        rows = conn.execute(f"SELECT rowid AS _rowid, * FROM {table} WHERE provider='tsdb'")
        rows_by_table[table] = list(rows)
        for row in rows_by_table[table]:
            league = row[league_col]
            candidates = [league] if league in names else list(names) if league is None else []
            for candidate in candidates:
                new_id = names[candidate].get(_name(row["team_name"] or ""))
                if new_id:
                    remember(candidate, row[id_col], new_id)

    json_rows = []
    for table, fields in (
        ("settings", ("default_include_teams", "default_exclude_teams")),
        ("event_epg_groups", ("include_teams", "exclude_teams")),
    ):
        for field in fields:
            if field not in columns(table):
                continue
            for row in conn.execute(f"SELECT rowid AS _rowid, {field} FROM {table}"):
                try:
                    entries = json.loads(row[field]) if row[field] else None
                except (TypeError, ValueError):
                    continue
                if not isinstance(entries, list):
                    continue
                json_rows.append((table, field, row["_rowid"], entries))
                for entry in entries:
                    if not isinstance(entry, dict) or entry.get("provider") != "tsdb":
                        continue
                    league = entry.get("league")
                    if isinstance(league, str) and league in names:
                        new_id = names[league].get(_name(entry.get("name") or ""))
                        if new_id:
                            remember(league, entry.get("team_id"), new_id)

    for table, league_col, id_col in sources:
        if table == "team_cache":
            continue
        for row in rows_by_table.get(table, []):
            league = row[league_col]
            candidates = [league] if league in names else list(names) if league is None else []
            resolved = {
                old_ids[candidate, str(row[id_col])]
                for candidate in candidates
                if (candidate, str(row[id_col])) in old_ids
            }
            if len(resolved) != 1:
                if candidates:
                    logger.warning(
                        "[MIGRATE] Cricket: cannot map %s row %s; preserved for review",
                        table,
                        row["_rowid"],
                    )
                continue
            try:
                conn.execute(
                    f"UPDATE {table} SET provider='espn', {id_col}=? WHERE rowid=?",
                    (resolved.pop(), row["_rowid"]),
                )
            except sqlite3.IntegrityError:
                # Never merge/delete two user channel configurations merely
                # because they happen to refer to the same sporting identity.
                logger.warning(
                    "[MIGRATE] Cricket: duplicate %s row %s; preserved for review",
                    table,
                    row["_rowid"],
                )

    for table, field, rowid, entries in json_rows:
        changed = False
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("provider") != "tsdb":
                continue
            league = entry.get("league")
            if not isinstance(league, str):
                continue
            key = (league, str(entry.get("team_id")))
            if key in old_ids:
                entry.update(provider="espn", team_id=old_ids[key])
                changed = True
            elif key[0] in names:
                logger.warning(
                    "[MIGRATE] Cricket: unmapped %s.%s selection; preserved for review",
                    table,
                    field,
                )
        if changed:
            conn.execute(
                f"UPDATE {table} SET {field}=? WHERE rowid=?", (json.dumps(entries), rowid)
            )

    for league in names:
        for table, league_col in (("team_cache", "league"), ("league_cache", "league_slug")):
            if league_col in columns(table):
                conn.execute(f"DELETE FROM {table} WHERE {league_col}=?", (league,))
        if {"cache_key"} <= columns("service_cache"):
            # Keys include both provider-independent and raw-provider variants.
            conn.execute("DELETE FROM service_cache WHERE cache_key LIKE ?", (f"%:{league}:%",))
        if {"league", "user_corrected"} <= columns("stream_match_cache"):
            conn.execute(
                "DELETE FROM stream_match_cache WHERE league=? AND user_corrected=0", (league,)
            )
    # Negative cache rows have no reliable league attribution. Pinned user
    # corrections (including explicit skips) must remain untouched.
    if {"event_id", "user_corrected"} <= columns("stream_match_cache"):
        conn.execute(
            "DELETE FROM stream_match_cache WHERE event_id='__FAILED__' AND user_corrected=0"
        )
