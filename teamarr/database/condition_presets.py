"""Database operations for condition presets.

Provides CRUD operations for the condition_presets table.
Condition presets store reusable condition configurations for template descriptions.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from sqlite3 import Connection
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ConditionPreset:
    """Condition preset configuration."""

    id: int | None = None
    name: str = ""
    description: str | None = None
    conditions: list[dict[str, Any]] = field(default_factory=list)
    created_at: datetime | None = None


def _row_to_preset(row) -> ConditionPreset:
    """Convert a database row to ConditionPreset."""
    conditions = []
    if row["conditions"]:
        try:
            conditions = json.loads(row["conditions"])
        except (json.JSONDecodeError, TypeError):
            pass

    created_at = None
    if row["created_at"]:
        try:
            created_at = datetime.fromisoformat(row["created_at"])
        except (ValueError, TypeError):
            pass

    return ConditionPreset(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        conditions=conditions,
        created_at=created_at,
    )


# =============================================================================
# READ OPERATIONS
# =============================================================================


def get_all_presets(conn: Connection) -> list[ConditionPreset]:
    """Get all condition presets.

    Args:
        conn: Database connection

    Returns:
        List of ConditionPreset objects
    """
    cursor = conn.execute("SELECT * FROM condition_presets ORDER BY name")
    return [_row_to_preset(row) for row in cursor.fetchall()]


def get_preset(conn: Connection, preset_id: int) -> ConditionPreset | None:
    """Get a single condition preset by ID.

    Args:
        conn: Database connection
        preset_id: Preset ID

    Returns:
        ConditionPreset or None if not found
    """
    cursor = conn.execute("SELECT * FROM condition_presets WHERE id = ?", (preset_id,))
    row = cursor.fetchone()
    return _row_to_preset(row) if row else None


def get_preset_by_name(conn: Connection, name: str) -> ConditionPreset | None:
    """Get a single condition preset by name.

    Args:
        conn: Database connection
        name: Preset name

    Returns:
        ConditionPreset or None if not found
    """
    cursor = conn.execute("SELECT * FROM condition_presets WHERE name = ?", (name,))
    row = cursor.fetchone()
    return _row_to_preset(row) if row else None


# =============================================================================
# CREATE OPERATIONS
# =============================================================================


def create_preset(
    conn: Connection,
    name: str,
    conditions: list[dict[str, Any]],
    description: str | None = None,
) -> int:
    """Create a new condition preset.

    Args:
        conn: Database connection
        name: Unique preset name
        conditions: List of condition configurations
        description: Optional description

    Returns:
        New preset ID
    """
    cursor = conn.execute(
        """INSERT INTO condition_presets (name, description, conditions)
           VALUES (?, ?, ?)""",
        (name, description, json.dumps(conditions)),
    )
    conn.commit()
    preset_id = cursor.lastrowid
    assert preset_id is not None  # just-inserted row always has a rowid
    logger.info("[CREATED] Condition preset id=%d name=%s", preset_id, name)
    return preset_id


# =============================================================================
# UPDATE OPERATIONS
# =============================================================================


def update_preset(
    conn: Connection,
    preset_id: int,
    name: str | None = None,
    description: str | None = None,
    conditions: list[dict[str, Any]] | None = None,
    clear_description: bool = False,
) -> bool:
    """Update a condition preset.

    Only updates fields that are explicitly provided (not None).

    Args:
        conn: Database connection
        preset_id: Preset ID to update
        name: New name
        description: New description
        conditions: New conditions list
        clear_description: Set description to NULL

    Returns:
        True if updated
    """
    updates = []
    values = []

    if name is not None:
        updates.append("name = ?")
        values.append(name)

    if description is not None:
        updates.append("description = ?")
        values.append(description)
    elif clear_description:
        updates.append("description = NULL")

    if conditions is not None:
        updates.append("conditions = ?")
        values.append(json.dumps(conditions))

    if not updates:
        return False

    values.append(preset_id)
    query = f"UPDATE condition_presets SET {', '.join(updates)} WHERE id = ?"
    cursor = conn.execute(query, values)
    conn.commit()
    if cursor.rowcount > 0:
        logger.info("[UPDATED] Condition preset id=%d", preset_id)
        return True
    return False


# =============================================================================
# DELETE OPERATIONS
# =============================================================================


def delete_preset(conn: Connection, preset_id: int) -> bool:
    """Delete a condition preset.

    Args:
        conn: Database connection
        preset_id: Preset ID to delete

    Returns:
        True if deleted
    """
    cursor = conn.execute("DELETE FROM condition_presets WHERE id = ?", (preset_id,))
    conn.commit()
    if cursor.rowcount > 0:
        logger.info("[DELETED] Condition preset id=%d", preset_id)
        return True
    return False
