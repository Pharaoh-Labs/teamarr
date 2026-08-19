"""Schema reconciliation — ensures all table columns match schema.sql.

Uses an in-memory reference database created from schema.sql to determine
the expected schema, then adds any missing columns to the real database.
This eliminates the need for version-gated column additions in migrations.

Adding a new column is now: just add it to schema.sql's CREATE TABLE.
Reconciliation handles existing databases automatically on next startup.
"""

import logging
import re
import sqlite3
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Tables to skip during reconciliation (internal/temporary)
_SKIP_TABLES = frozenset({"sqlite_sequence"})

# Defaults that ALTER TABLE ADD COLUMN accepts (constants only —
# CURRENT_TIMESTAMP and expressions are rejected by SQLite for ADD COLUMN)
_CONSTANT_DEFAULT = re.compile(
    r"^(NULL|TRUE|FALSE|-?\d+(\.\d+)?|'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\")$",
    re.IGNORECASE,
)


def _split_top_level(body: str) -> list[str]:
    """Split a CREATE TABLE body on top-level commas.

    Respects parentheses (CHECK(...)), quoted identifiers/strings, and SQL
    comments, so commas inside them don't split.
    """
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        # Line comment: skip to end of line
        if ch == "-" and body[i : i + 2] == "--":
            while i < n and body[i] != "\n":
                i += 1
            continue
        # Block comment: skip to closing */
        if ch == "/" and body[i : i + 2] == "/*":
            end = body.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        # Quoted string/identifier: copy verbatim to closing quote
        if ch in ("'", '"', "`", "["):
            close = "]" if ch == "[" else ch
            buf.append(ch)
            i += 1
            while i < n:
                buf.append(body[i])
                if body[i] == close:
                    i += 1
                    break
                i += 1
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    tail = "".join(buf).strip()
    if tail:
        parts.append(tail)
    return parts


def _extract_column_def(create_sql: str, col_name: str) -> str | None:
    """Extract a column's verbatim definition from a CREATE TABLE statement.

    Returns the full definition text (type, NOT NULL, DEFAULT, CHECK, ...)
    exactly as written in schema.sql, or None if not found.
    """
    start = create_sql.find("(")
    end = create_sql.rfind(")")
    if start == -1 or end <= start:
        return None

    for part in _split_top_level(create_sql[start + 1 : end]):
        tokens = part.split()
        if not tokens:
            continue
        ident = tokens[0].strip("\"'`[]")
        if ident.lower() == col_name.lower():
            # Collapse newlines/indentation to a single-line definition
            return " ".join(part.split())
    return None


def _fallback_column_def(col: sqlite3.Row) -> str:
    """Build a minimal column definition from PRAGMA table_info.

    Used when the verbatim definition can't be applied (e.g. UNIQUE, NOT
    NULL without default, or non-constant defaults — all illegal in ALTER
    TABLE ADD COLUMN). Drops constraints so the upgrade still succeeds;
    non-constant defaults (CURRENT_TIMESTAMP) are omitted since SQLite
    rejects them for added columns.
    """
    col_def = col["type"] or ""
    default = col["dflt_value"]
    if default is not None and _CONSTANT_DEFAULT.match(str(default).strip()):
        col_def += f" DEFAULT {default}"
    return col_def


@dataclass
class ReconcileResult:
    """Result of a schema reconciliation run."""

    tables_checked: int = 0
    columns_added: int = 0
    columns_by_table: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def reconcile_schema(
    conn: sqlite3.Connection, schema_sql: str
) -> ReconcileResult:
    """Ensure all table columns match schema.sql definitions.

    Creates an in-memory reference database from schema.sql, then compares
    each real table's columns against it. Missing columns are added via
    ALTER TABLE ADD COLUMN.

    Args:
        conn: Real database connection
        schema_sql: Contents of schema.sql

    Returns:
        ReconcileResult with counts and details
    """
    result = ReconcileResult()

    # Build reference schema in memory
    try:
        ref = sqlite3.connect(":memory:")
        ref.row_factory = sqlite3.Row
        ref.executescript(schema_sql)
    except Exception as e:
        logger.error("[RECONCILE] Failed to create reference schema: %s", e)
        result.errors.append(f"Reference schema failed: {e}")
        return result

    try:
        # Get tables from the real database
        real_tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\'"
            ).fetchall()
        }

        # Get tables from the reference
        ref_tables = {
            row[0]
            for row in ref.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name NOT LIKE '\\_%' ESCAPE '\\'"
            ).fetchall()
        }

        # Only reconcile tables that exist in both
        common_tables = (real_tables & ref_tables) - _SKIP_TABLES

        for table in sorted(common_tables):
            result.tables_checked += 1
            added = _reconcile_table(conn, ref, table, result)
            if added:
                result.columns_by_table[table] = added
                result.columns_added += len(added)

    finally:
        ref.close()

    return result


def _reconcile_table(
    conn: sqlite3.Connection,
    ref: sqlite3.Connection,
    table: str,
    result: ReconcileResult,
) -> list[str]:
    """Reconcile a single table's columns against the reference.

    Returns list of column names that were added.
    """
    # Get actual columns
    actual_cols = {
        row["name"] for row in conn.execute(f"PRAGMA table_info([{table}])").fetchall()
    }
    if not actual_cols:
        return []  # Table exists but has no columns (shouldn't happen)

    # Get expected columns from reference
    ref_cols = ref.execute(f"PRAGMA table_info([{table}])").fetchall()

    # Reference CREATE TABLE text — source of verbatim column definitions
    # (PRAGMA table_info drops NOT NULL/CHECK, which made upgraded databases
    # diverge from fresh installs)
    create_row = ref.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    create_sql = create_row["sql"] if create_row else ""

    added = []
    for col in ref_cols:
        col_name = col["name"]
        if col_name in actual_cols:
            continue

        # Prefer the verbatim schema.sql definition (keeps NOT NULL, CHECK,
        # DEFAULT); fall back to a minimal type+default definition for the
        # cases ALTER TABLE ADD COLUMN can't express (UNIQUE/PRIMARY KEY,
        # NOT NULL without default, non-constant defaults)
        verbatim = _extract_column_def(create_sql, col_name)
        fallback = f"[{col_name}] {_fallback_column_def(col)}".strip()
        candidates = [verbatim] if verbatim else []
        if fallback not in candidates:
            candidates.append(fallback)

        last_error: Exception | None = None
        for idx, col_def in enumerate(candidates):
            try:
                conn.execute(f"ALTER TABLE [{table}] ADD COLUMN {col_def}")
                added.append(col_name)
                logger.info("[RECONCILE] Added %s.%s (%s)", table, col_name, col_def)
                if idx > 0:
                    logger.warning(
                        "[RECONCILE] %s.%s added WITHOUT full constraints "
                        "(schema.sql def %r not applicable via ALTER): %s",
                        table,
                        col_name,
                        candidates[0],
                        last_error,
                    )
                last_error = None
                break
            except sqlite3.OperationalError as e:
                last_error = e

        if last_error is not None:
            msg = f"Failed to add {table}.{col_name}: {last_error}"
            result.errors.append(msg)
            logger.warning("[RECONCILE] %s", msg)

    return added
