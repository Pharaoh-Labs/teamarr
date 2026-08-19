"""Tests for BackupService, focused on path-traversal hardening.

The API routes validate filenames, but BackupService must independently refuse
to let a caller-supplied filename escape the backup directory (defence in depth
against CodeQL path-injection alerts #10-#25).
"""

import sqlite3
from pathlib import Path

import pytest

from teamarr.services.backup_service import BackupService


@pytest.fixture
def backup_dir(tmp_path):
    d = tmp_path / "backups"
    d.mkdir()
    return d


@pytest.fixture
def service(backup_dir):
    # db_factory is unused by the filename-handling paths under test.
    return BackupService(db_factory=lambda: None, backup_path=str(backup_dir))


def _make_backup_file(backup_dir: Path, name: str = "teamarr_manual_20240101_000000.db") -> Path:
    p = backup_dir / name
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.close()
    return p


@pytest.mark.parametrize("name", ["../secret.db", "../../etc/passwd", "/etc/passwd", "..", "."])
def test_resolve_backup_file_rejects_traversal(service, name):
    with pytest.raises(ValueError):
        service._resolve_backup_file(name)


def test_resolve_backup_file_accepts_plain_name(service, backup_dir):
    resolved = service._resolve_backup_file("teamarr_manual_20240101_000000.db")
    assert resolved.parent == backup_dir.resolve()
    assert resolved.name == "teamarr_manual_20240101_000000.db"


def test_delete_backup_rejects_traversal(service, backup_dir, tmp_path):
    # A real file outside the backup dir that a traversal name would target.
    outside = tmp_path / "outside.db"
    outside.write_text("keep me")

    assert service.delete_backup("../outside.db") is False
    assert outside.exists(), "traversal filename must not delete files outside backup dir"


def test_delete_backup_works_for_valid_name(service, backup_dir):
    _make_backup_file(backup_dir)
    assert service.delete_backup("teamarr_manual_20240101_000000.db") is True
    assert not (backup_dir / "teamarr_manual_20240101_000000.db").exists()


def test_get_backup_filepath_rejects_traversal(service, tmp_path):
    outside = tmp_path / "outside.db"
    outside.write_text("data")
    assert service.get_backup_filepath("../outside.db") is None


def test_protect_and_unprotect_reject_traversal(service):
    assert service.protect_backup("../secret.db") is False
    assert service.unprotect_backup("../secret.db") is False


def test_restore_backup_rejects_traversal(service):
    success, message, path = service.restore_backup("../../etc/passwd")
    assert success is False
    assert message == "Invalid backup filename"
    assert path is None
