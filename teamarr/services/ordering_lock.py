"""Kernel locks shared by workers using the same Teamarr data volume.

Locks live beside the SQLite database; replicas must share both the database
and its directory. Never unlink a lock file (that would split the lock domain).
"""

import fcntl
import threading
from typing import TextIO

from teamarr.database.connection import resolve_db_path


class ProcessLock:
    """threading.Lock-compatible, crash-released cross-process exclusion."""

    def __init__(self, name: str):
        self.name = name
        self._thread_lock = threading.Lock()
        self._file: TextIO | None = None

    def acquire(self, blocking: bool = True) -> bool:
        if not self._thread_lock.acquire(blocking=blocking):
            return False
        try:
            path = resolve_db_path(None).with_suffix(f".{self.name}.lock")
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("a")
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
            except BlockingIOError:
                handle.close()
                self._thread_lock.release()
                return False
            except BaseException:
                handle.close()
                raise
            self._file = handle
            return True
        except BaseException:
            self._thread_lock.release()
            raise

    def release(self) -> None:
        handle, self._file = self._file, None
        if handle is None:
            raise RuntimeError("release unlocked ordering lock")
        handle.close()
        self._thread_lock.release()

    def locked(self) -> bool:
        return self._thread_lock.locked()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()
