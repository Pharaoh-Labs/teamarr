"""Shared path constants for the test suite.

Tests live at varying depths under tests/ — never compute the repo root from
a test file's own __file__ (it breaks when the file moves); import it here.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = REPO_ROOT / "teamarr" / "database" / "schema.sql"
