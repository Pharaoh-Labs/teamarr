"""Database operations for consolidation exception keywords.

Provides CRUD operations for the consolidation_exception_keywords table.
Exception keywords control how duplicate streams are handled during event matching.
"""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from functools import cached_property
from sqlite3 import Connection
from typing import Any, Literal

logger = logging.getLogger(__name__)

ExceptionBehavior = Literal["consolidate", "separate", "ignore"]


@dataclass
class ExceptionKeyword:
    """Consolidation exception keyword configuration.

    Attributes:
        label: Primary identifier used in channel names and {exception_keyword} template variable
        match_terms: Comma-separated phrases/words to match in stream names
        behavior: How to handle matched streams (consolidate/separate/ignore)
    """

    id: int | None = None
    label: str = ""  # Used for channel naming and {exception_keyword} variable
    match_terms: str = ""  # Comma-separated terms to match
    behavior: ExceptionBehavior = "consolidate"
    enabled: bool = True
    created_at: datetime | None = None
    # Match sources beyond stream-name terms (#893). Picked groups/streams are
    # [{"id": int, "name": str}]; the name is a display snapshot only.
    m3u_group_pattern: str | None = None
    m3u_groups: list[dict] = field(default_factory=list)
    stream_pattern: str | None = None
    streams: list[dict] = field(default_factory=list)
    event_group_ids: list[int] = field(default_factory=list)

    @property
    def match_term_list(self) -> list[str]:
        """Get match terms as a list."""
        return [k.strip() for k in self.match_terms.split(",") if k.strip()]

    @cached_property
    def m3u_group_regex(self) -> re.Pattern | None:
        return compile_source_pattern(self.m3u_group_pattern)

    @cached_property
    def stream_regex(self) -> re.Pattern | None:
        return compile_source_pattern(self.stream_pattern)

    @cached_property
    def m3u_group_id_set(self) -> frozenset[int]:
        return _id_set(self.m3u_groups)

    @cached_property
    def stream_id_set(self) -> frozenset[int]:
        return _id_set(self.streams)

    @cached_property
    def event_group_id_set(self) -> frozenset[int]:
        return frozenset(i for i in self.event_group_ids if isinstance(i, int))

    @property
    def uses_m3u_group(self) -> bool:
        """Whether this keyword can match on a stream's M3U group."""
        return bool(self.m3u_group_id_set or self.m3u_group_regex)


def compile_source_pattern(pattern: str | None) -> re.Pattern | None:
    """Compile a match-source regex, or None if empty/invalid.

    Case-insensitive search, the same semantics as the event-group
    ``m3u_group_name_pattern``. The API rejects invalid patterns; an invalid
    one already stored is skipped rather than failing every match.
    """
    if not pattern or not pattern.strip():
        return None
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        logger.warning("[KEYWORD] Invalid match-source pattern %r: %s", pattern, e)
        return None


def _id_set(items: list[dict]) -> frozenset[int]:
    return frozenset(
        item["id"] for item in items if isinstance(item, dict) and isinstance(item.get("id"), int)
    )


def _load_json_list(raw: Any) -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def _dump_json_list(value: list | None) -> str | None:
    return json.dumps(value) if value else None


def _row_to_keyword(row) -> ExceptionKeyword:
    """Convert a database row to ExceptionKeyword."""
    created_at = None
    if row["created_at"]:
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (ValueError, TypeError):
            pass

    keys = row.keys()

    def col(name: str) -> Any:
        # Missing on a DB not yet reconciled (tests with partial schemas).
        return row[name] if name in keys else None

    return ExceptionKeyword(
        id=row["id"],
        label=row["label"] or "",
        match_terms=row["match_terms"] or "",
        behavior=row["behavior"] or "consolidate",
        enabled=bool(row["enabled"]),
        created_at=created_at,
        m3u_group_pattern=col("m3u_group_pattern") or None,
        m3u_groups=_load_json_list(col("m3u_groups")),
        stream_pattern=col("stream_pattern") or None,
        streams=_load_json_list(col("streams")),
        event_group_ids=_load_json_list(col("event_group_ids")),
    )


# =============================================================================
# READ OPERATIONS
# =============================================================================


def get_all_keywords(conn: Connection, include_disabled: bool = False) -> list[ExceptionKeyword]:
    """Get all exception keywords.

    Args:
        conn: Database connection
        include_disabled: Include disabled keywords

    Returns:
        List of ExceptionKeyword objects
    """
    if include_disabled:
        cursor = conn.execute("SELECT * FROM consolidation_exception_keywords ORDER BY label")
    else:
        cursor = conn.execute(
            """SELECT * FROM consolidation_exception_keywords
               WHERE enabled = 1 ORDER BY label"""
        )

    return [_row_to_keyword(row) for row in cursor.fetchall()]


def get_keyword(conn: Connection, keyword_id: int) -> ExceptionKeyword | None:
    """Get a single exception keyword by ID.

    Args:
        conn: Database connection
        keyword_id: Keyword ID

    Returns:
        ExceptionKeyword or None if not found
    """
    cursor = conn.execute(
        "SELECT * FROM consolidation_exception_keywords WHERE id = ?", (keyword_id,)
    )
    row = cursor.fetchone()
    return _row_to_keyword(row) if row else None


def get_keywords_by_behavior(
    conn: Connection, behavior: ExceptionBehavior
) -> list[ExceptionKeyword]:
    """Get all enabled keywords with a specific behavior.

    Args:
        conn: Database connection
        behavior: Behavior type to filter by

    Returns:
        List of ExceptionKeyword objects
    """
    cursor = conn.execute(
        """SELECT * FROM consolidation_exception_keywords
           WHERE behavior = ? AND enabled = 1
           ORDER BY label""",
        (behavior,),
    )
    return [_row_to_keyword(row) for row in cursor.fetchall()]


# =============================================================================
# CREATE OPERATIONS
# =============================================================================


def create_keyword(
    conn: Connection,
    label: str,
    match_terms: str,
    behavior: ExceptionBehavior = "consolidate",
    enabled: bool = True,
    *,
    m3u_group_pattern: str | None = None,
    m3u_groups: list[dict] | None = None,
    stream_pattern: str | None = None,
    streams: list[dict] | None = None,
    event_group_ids: list[int] | None = None,
) -> int:
    """Create a new exception keyword entry.

    Args:
        conn: Database connection
        label: Label for channel naming and {exception_keyword} variable
        match_terms: Comma-separated terms to match in stream names ('' when
            the keyword matches on its other sources only)
        behavior: How to handle matched streams
        enabled: Whether the keyword is active
        m3u_group_pattern, m3u_groups, stream_pattern, streams, event_group_ids:
            Match sources (#893), see ExceptionKeyword

    Returns:
        New keyword ID
    """
    cursor = conn.execute(
        """INSERT INTO consolidation_exception_keywords
           (label, match_terms, behavior, enabled, m3u_group_pattern, m3u_groups,
            stream_pattern, streams, event_group_ids)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            label,
            match_terms,
            behavior,
            int(enabled),
            m3u_group_pattern or None,
            _dump_json_list(m3u_groups),
            stream_pattern or None,
            _dump_json_list(streams),
            _dump_json_list(event_group_ids),
        ),
    )
    conn.commit()
    keyword_id = cursor.lastrowid
    assert keyword_id is not None  # just-inserted row always has a rowid
    logger.info("[CREATED] Exception keyword id=%d label=%s", keyword_id, label)
    return keyword_id


# =============================================================================
# UPDATE OPERATIONS
# =============================================================================


def update_keyword(
    conn: Connection,
    keyword_id: int,
    label: str | None = None,
    match_terms: str | None = None,
    behavior: ExceptionBehavior | None = None,
    enabled: bool | None = None,
    *,
    m3u_group_pattern: str | None = None,
    m3u_groups: list[dict] | None = None,
    stream_pattern: str | None = None,
    streams: list[dict] | None = None,
    event_group_ids: list[int] | None = None,
) -> bool:
    """Update an exception keyword.

    Only updates fields that are explicitly provided (not None). For the
    match sources, an empty string/list clears the source.

    Args:
        conn: Database connection
        keyword_id: Keyword ID to update
        label: New label for channel naming
        match_terms: New match terms string
        behavior: New behavior
        enabled: New enabled status

    Returns:
        True if updated
    """
    updates = []
    values = []

    if label is not None:
        updates.append("label = ?")
        values.append(label)

    if match_terms is not None:
        updates.append("match_terms = ?")
        values.append(match_terms)

    if behavior is not None:
        updates.append("behavior = ?")
        values.append(behavior)

    if enabled is not None:
        updates.append("enabled = ?")
        values.append(int(enabled))

    for column, text in (
        ("m3u_group_pattern", m3u_group_pattern),
        ("stream_pattern", stream_pattern),
    ):
        if text is not None:
            updates.append(f"{column} = ?")
            values.append(text or None)

    for column, items in (
        ("m3u_groups", m3u_groups),
        ("streams", streams),
        ("event_group_ids", event_group_ids),
    ):
        if items is not None:
            updates.append(f"{column} = ?")
            values.append(_dump_json_list(items))

    if not updates:
        return False

    values.append(keyword_id)
    query = f"UPDATE consolidation_exception_keywords SET {', '.join(updates)} WHERE id = ?"
    cursor = conn.execute(query, values)
    conn.commit()
    if cursor.rowcount > 0:
        logger.info("[UPDATED] Exception keyword id=%d", keyword_id)
        return True
    return False


def set_keyword_enabled(conn: Connection, keyword_id: int, enabled: bool) -> bool:
    """Enable or disable an exception keyword.

    Args:
        conn: Database connection
        keyword_id: Keyword ID
        enabled: New enabled status

    Returns:
        True if updated
    """
    cursor = conn.execute(
        "UPDATE consolidation_exception_keywords SET enabled = ? WHERE id = ?",
        (int(enabled), keyword_id),
    )
    conn.commit()
    if cursor.rowcount > 0:
        logger.info("[UPDATED] Exception keyword id=%d enabled=%s", keyword_id, enabled)
        return True
    return False


# =============================================================================
# DELETE OPERATIONS
# =============================================================================


def delete_keyword(conn: Connection, keyword_id: int) -> bool:
    """Delete an exception keyword.

    Args:
        conn: Database connection
        keyword_id: Keyword ID to delete

    Returns:
        True if deleted
    """
    cursor = conn.execute(
        "DELETE FROM consolidation_exception_keywords WHERE id = ?", (keyword_id,)
    )
    conn.commit()
    if cursor.rowcount > 0:
        logger.info("[DELETED] Exception keyword id=%d", keyword_id)
        return True
    return False


# =============================================================================
# DEFAULT SEED (#726)
# =============================================================================
# These used to be an `INSERT OR IGNORE` block in schema.sql, which
# `conn.executescript` replays on EVERY startup — so a default the user
# deleted came straight back on the next restart. Seeding is now a one-shot
# per label, recorded in `seeded_default_exception_keywords`: a label listed
# there is never offered again, which makes a delete (or a rename away from
# the default label) permanent. New defaults added in a later release still
# reach existing installs, because only the labels already seeded are skipped.

DEFAULT_EXCEPTION_KEYWORDS: tuple[tuple[str, str, ExceptionBehavior], ...] = (
    ("Spanish", "Spanish, En Español, (ESP), Español", "consolidate"),
    ("French", "French, En Français, (FRA), Français", "consolidate"),
    ("German", "German, (GER), Deutsch", "consolidate"),
    ("Portuguese", "Portuguese, (POR), Português", "consolidate"),
    ("Italian", "Italian, (ITA), Italiano", "consolidate"),
    ("Japanese", "Japanese, (JPN), 日本語", "consolidate"),
    ("Korean", "Korean, (KOR), 한국어", "consolidate"),
    ("Chinese", "Chinese, (CHN), (CHI), 中文", "consolidate"),
)


def get_seeded_default_labels(conn: Connection) -> set[str]:
    """Default labels this install has already been seeded (see #726)."""
    try:
        rows = conn.execute("SELECT label FROM seeded_default_exception_keywords").fetchall()
    except Exception:
        return set()  # pre-reconciliation startup order safety
    return {row[0] for row in rows}


def mark_defaults_seeded(conn: Connection, labels: set[str]) -> None:
    """Record labels as already seeded so they are never re-inserted."""
    conn.executemany(
        "INSERT OR IGNORE INTO seeded_default_exception_keywords (label) VALUES (?)",
        [(label,) for label in sorted(labels)],
    )


def seed_default_exception_keywords(conn: Connection) -> int:
    """Seed the default language keywords, once per label per install.

    Idempotent and safe on every startup: a label already recorded in
    `seeded_default_exception_keywords` is skipped even if the row is gone,
    so user deletions stick. Returns the number of rows created.
    """
    already_seeded = get_seeded_default_labels(conn)
    pending = [spec for spec in DEFAULT_EXCEPTION_KEYWORDS if spec[0] not in already_seeded]
    if not pending:
        return 0

    created = 0
    for label, match_terms, behavior in pending:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO consolidation_exception_keywords
               (label, match_terms, behavior)
               VALUES (?, ?, ?)""",
            (label, match_terms, behavior),
        )
        created += cursor.rowcount

    # Mark every pending label, including ones an existing row shadowed — the
    # point is "offered once", not "inserted once".
    mark_defaults_seeded(conn, {spec[0] for spec in pending})
    conn.commit()

    if created:
        logger.info("[SEED] Created %d default exception keyword(s)", created)
    return created
