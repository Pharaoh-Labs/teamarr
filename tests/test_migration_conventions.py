"""Static-analysis tests for migration conventions.

Pins the rules documented in teamarr/database/MIGRATIONS.md so they don't
silently drift back into bad patterns:

  - Schema (column shape) lives in schema.sql, enforced by reconciliation.
  - _run_migrations() body is a list of guarded helper calls only.
  - Migration helpers do data transforms, not column-add boilerplate.
  - Every if-block in _run_migrations advances schema_version.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

CONNECTION_PY = Path(__file__).parent.parent / "teamarr" / "database" / "connection.py"


@pytest.fixture(scope="module")
def connection_source() -> str:
    return CONNECTION_PY.read_text()


@pytest.fixture(scope="module")
def connection_ast(connection_source: str) -> ast.Module:
    return ast.parse(connection_source)


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"function {name!r} not found in connection.py")


def test_run_migrations_body_is_only_helper_calls(connection_ast: ast.Module):
    """_run_migrations should be a series of guarded `if` blocks calling helpers.

    No inline conn.execute() calls — they belong inside named migration
    helpers or the bootstrap helpers (_get_current_schema_version,
    _recover_schema_version_from_v65_backup_if_needed).
    """
    fn = _find_function(connection_ast, "_run_migrations")

    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        if func.attr != "execute":
            continue
        if not (isinstance(func.value, ast.Name) and func.value.id == "conn"):
            continue
        pytest.fail(
            f"_run_migrations contains inline conn.execute() at line "
            f"{node.lineno}. Move into a _migrate_v*_* helper or one of the "
            f"bootstrap helpers (_get_current_schema_version, "
            f"_recover_schema_version_from_v65_backup_if_needed)."
        )


def test_migration_blocks_advance_schema_version(connection_source: str):
    """Every `if current_version < N:` block must contain a `current_version = N` line.

    Catches the bug where you forget to bump the local var, causing later
    blocks to also run when they shouldn't.
    """
    body = _extract_run_migrations_body(connection_source)
    pattern = re.compile(
        r"^\s*if current_version < (\d+):\s*\n(.*?)(?=^\s*if current_version|^\s*$|\Z)",
        re.MULTILINE | re.DOTALL,
    )

    for match in pattern.finditer(body):
        target = match.group(1)
        block = match.group(2)
        bump = f"current_version = {target}"
        assert bump in block, (
            f"if-block guarding v{target} does not set `current_version = {target}` "
            f"after running. Block: {block.strip()[:200]!r}"
        )


def test_no_inline_alter_table_add_column_in_run_migrations(connection_source: str):
    """ALTER TABLE ADD COLUMN in _run_migrations body indicates schema drift.

    Allowed: inside named _migrate_v*_* helper functions (defensive against
    test paths that bypass reconciliation). Forbidden: inline in the
    _run_migrations driver itself.
    """
    body = _extract_run_migrations_body(connection_source)
    assert "ADD COLUMN" not in body.upper(), (
        "_run_migrations body contains ALTER TABLE ADD COLUMN inline. "
        "Add the column to schema.sql instead — reconciliation will create it. "
        "If the migration also needs the column for a data transform, put "
        "_add_column_if_not_exists inside the _migrate_v*_* helper."
    )


def test_migration_helpers_named_with_version_prefix(connection_ast: ast.Module):
    """Functions named `_migrate_v*` should follow the `_migrate_v{N}_{desc}` pattern."""
    pattern = re.compile(r"^_migrate_v\d+(_\w+)?$")
    for node in connection_ast.body:
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_migrate_v"):
            assert pattern.match(node.name), (
                f"migration helper {node.name!r} does not match _migrate_v{{N}}_{{desc}}"
            )


def test_apply_migration_signature_is_stable(connection_ast: ast.Module):
    """_apply_migration must accept (conn, target, description, fn).

    Catches accidental signature changes that would silently break callers.
    """
    fn = _find_function(connection_ast, "_apply_migration")
    arg_names = [a.arg for a in fn.args.args]
    assert arg_names == ["conn", "target", "description", "migration_fn"], (
        f"_apply_migration signature drifted: {arg_names}"
    )


def test_advance_version_signature_is_stable(connection_ast: ast.Module):
    fn = _find_function(connection_ast, "_advance_version")
    arg_names = [a.arg for a in fn.args.args]
    assert arg_names == ["conn", "target", "reason"], (
        f"_advance_version signature drifted: {arg_names}"
    )


def _extract_run_migrations_body(source: str) -> str:
    """Extract the body of _run_migrations as a string (for substring checks)."""
    lines = source.splitlines()
    start = None
    indent_level = None
    body_lines: list[str] = []
    for i, line in enumerate(lines):
        if start is None:
            if re.match(r"^def _run_migrations\(", line):
                start = i
            continue
        # First non-blank line after def gives us the body indent.
        if indent_level is None and line.strip():
            indent_level = len(line) - len(line.lstrip())
            body_lines.append(line)
            continue
        # End of function: a top-level `def ` or `class ` at column 0.
        if line and not line.startswith(" ") and not line.startswith("\t"):
            break
        body_lines.append(line)
    assert start is not None, "could not locate _run_migrations in source"
    return "\n".join(body_lines)


def test_extract_helper_works(connection_source: str):
    """Sanity check: the body extractor returns something sensible."""
    body = _extract_run_migrations_body(connection_source)
    assert "current_version" in body
    assert "_apply_migration" in body
    assert "def _run_migrations" not in body  # body excludes the def line
