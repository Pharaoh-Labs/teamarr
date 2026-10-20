"""Detection keywords database operations.

CRUD queries for user-defined detection patterns stored in the
detection_keywords table.
"""

import logging
from sqlite3 import Connection

logger = logging.getLogger(__name__)


def list_keywords(
    conn: Connection,
    category: str | None = None,
    enabled_only: bool = False,
) -> list[dict]:
    """List detection keywords with optional filters.

    Args:
        conn: Database connection
        category: Optional category filter
        enabled_only: If True, only return enabled keywords

    Returns:
        List of keyword row dicts
    """
    query = "SELECT * FROM detection_keywords WHERE 1=1"
    params: list = []

    if category:
        query += " AND category = ?"
        params.append(category)

    if enabled_only:
        query += " AND enabled = 1"

    query += " ORDER BY category, priority DESC, keyword"

    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_keyword(conn: Connection, keyword_id: int) -> dict | None:
    """Get a single detection keyword by ID.

    Args:
        conn: Database connection
        keyword_id: Keyword ID

    Returns:
        Keyword row dict, or None if not found
    """
    row = conn.execute("SELECT * FROM detection_keywords WHERE id = ?", (keyword_id,)).fetchone()
    return dict(row) if row else None


def create_keyword(
    conn: Connection,
    category: str,
    keyword: str,
    is_regex: bool = False,
    target_value: str | None = None,
    enabled: bool = True,
    priority: int = 0,
    description: str | None = None,
) -> dict:
    """Create a detection keyword.

    Args:
        conn: Database connection
        category: Keyword category
        keyword: The keyword/pattern text
        is_regex: Whether the keyword is a regex
        target_value: Optional target value mapping
        enabled: Whether the keyword is active
        priority: Sort priority
        description: Optional description

    Returns:
        The created keyword row dict

    Raises:
        sqlite3.IntegrityError: If keyword already exists in category
    """
    cursor = conn.execute(
        """INSERT INTO detection_keywords
           (category, keyword, is_regex, target_value, enabled, priority, description)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (category, keyword, int(is_regex), target_value, int(enabled), priority, description),
    )
    conn.commit()
    keyword_id = cursor.lastrowid

    logger.info(
        "[DETECTION_KW] Created keyword id=%d category=%s keyword=%s",
        keyword_id,
        category,
        keyword,
    )

    row = conn.execute("SELECT * FROM detection_keywords WHERE id = ?", (keyword_id,)).fetchone()
    return dict(row)


def update_keyword(
    conn: Connection,
    keyword_id: int,
    *,
    keyword: str | None = None,
    is_regex: bool | None = None,
    target_value: str | None = None,
    clear_target_value: bool = False,
    enabled: bool | None = None,
    priority: int | None = None,
    description: str | None = None,
    clear_description: bool = False,
) -> dict | None:
    """Update a detection keyword.

    Args:
        conn: Database connection
        keyword_id: Keyword ID
        keyword: New keyword text
        is_regex: New regex flag
        target_value: New target value
        clear_target_value: Set target_value to NULL
        enabled: New enabled flag
        priority: New priority
        description: New description
        clear_description: Set description to NULL

    Returns:
        Updated keyword row dict, or None if not found
    """
    existing = conn.execute(
        "SELECT * FROM detection_keywords WHERE id = ?", (keyword_id,)
    ).fetchone()
    if not existing:
        return None

    updates = ["updated_at = CURRENT_TIMESTAMP"]
    values: list = []

    if keyword is not None:
        updates.append("keyword = ?")
        values.append(keyword)

    if is_regex is not None:
        updates.append("is_regex = ?")
        values.append(int(is_regex))

    if target_value is not None:
        updates.append("target_value = ?")
        values.append(target_value)
    elif clear_target_value:
        updates.append("target_value = NULL")

    if enabled is not None:
        updates.append("enabled = ?")
        values.append(int(enabled))

    if priority is not None:
        updates.append("priority = ?")
        values.append(priority)

    if description is not None:
        updates.append("description = ?")
        values.append(description)
    elif clear_description:
        updates.append("description = NULL")

    if len(updates) > 1:  # More than just updated_at
        values.append(keyword_id)
        conn.execute(
            f"UPDATE detection_keywords SET {', '.join(updates)} WHERE id = ?",
            values,
        )
        conn.commit()
        logger.info("[DETECTION_KW] Updated keyword id=%d", keyword_id)

    row = conn.execute("SELECT * FROM detection_keywords WHERE id = ?", (keyword_id,)).fetchone()
    return dict(row)


def delete_keyword(conn: Connection, keyword_id: int) -> dict | None:
    """Delete a detection keyword.

    Args:
        conn: Database connection
        keyword_id: Keyword ID

    Returns:
        Deleted keyword info (category, keyword) or None if not found
    """
    existing = conn.execute(
        "SELECT * FROM detection_keywords WHERE id = ?", (keyword_id,)
    ).fetchone()
    if not existing:
        return None

    conn.execute("DELETE FROM detection_keywords WHERE id = ?", (keyword_id,))
    conn.commit()

    logger.info(
        "[DETECTION_KW] Deleted keyword id=%d category=%s keyword=%s",
        keyword_id,
        existing["category"],
        existing["keyword"],
    )
    return {"id": keyword_id, "category": existing["category"], "keyword": existing["keyword"]}


def bulk_import_keywords(
    conn: Connection,
    keywords: list[dict],
    replace_category: bool = False,
) -> tuple[int, int, int, list[str]]:
    """Bulk import detection keywords with upsert.

    Args:
        conn: Database connection
        keywords: List of keyword dicts with keys:
            category, keyword, is_regex, target_value, enabled, priority, description
        replace_category: If True, delete existing keywords in each category first

    Returns:
        Tuple of (created, updated, failed, errors)
    """
    created = 0
    updated = 0
    failed = 0
    errors: list[str] = []

    if replace_category:
        categories = set(kw["category"] for kw in keywords)
        for cat in categories:
            conn.execute("DELETE FROM detection_keywords WHERE category = ?", (cat,))
            logger.info("[DETECTION_KW] Cleared category %s for replace import", cat)

    for kw in keywords:
        try:
            cursor = conn.execute(
                """INSERT INTO detection_keywords
                   (category, keyword, is_regex, target_value, enabled, priority, description)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(category, keyword) DO UPDATE SET
                   is_regex = excluded.is_regex,
                   target_value = excluded.target_value,
                   enabled = excluded.enabled,
                   priority = excluded.priority,
                   description = excluded.description,
                   updated_at = CURRENT_TIMESTAMP""",
                (
                    kw["category"],
                    kw["keyword"],
                    int(kw.get("is_regex", False)),
                    kw.get("target_value"),
                    int(kw.get("enabled", True)),
                    kw.get("priority", 0),
                    kw.get("description"),
                ),
            )
            if cursor.rowcount > 0:
                existing = conn.execute(
                    """SELECT created_at, updated_at FROM detection_keywords
                       WHERE category = ? AND keyword = ?""",
                    (kw["category"], kw["keyword"]),
                ).fetchone()
                if existing and existing["created_at"] == existing["updated_at"]:
                    created += 1
                else:
                    updated += 1
        except Exception as e:
            failed += 1
            errors.append(f"{kw['category']}/{kw['keyword']}: {e}")

    conn.commit()

    logger.info(
        "[DETECTION_KW] Bulk import: created=%d updated=%d failed=%d",
        created,
        updated,
        failed,
    )
    return created, updated, failed, errors


def export_keywords(
    conn: Connection,
    category: str | None = None,
) -> list[dict]:
    """Export detection keywords as plain dicts.

    Args:
        conn: Database connection
        category: Optional category filter

    Returns:
        List of keyword export dicts
    """
    query = "SELECT * FROM detection_keywords"
    params: list = []

    if category:
        query += " WHERE category = ?"
        params.append(category)

    query += " ORDER BY category, priority DESC, keyword"

    rows = conn.execute(query, params).fetchall()
    return [
        {
            "category": row["category"],
            "keyword": row["keyword"],
            "is_regex": bool(row["is_regex"]),
            "target_value": row["target_value"],
            "enabled": bool(row["enabled"]),
            "priority": row["priority"] or 0,
            "description": row["description"],
        }
        for row in rows
    ]
