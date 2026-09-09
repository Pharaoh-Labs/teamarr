"""Process-local status for detached media-server guide refreshes."""

from dataclasses import dataclass, field
from threading import Lock


@dataclass
class MediaRefreshStatus:
    """The currently active serialized media refresh batch."""

    in_progress: bool = False
    status: str = "idle"
    message: str = ""
    current: int = 0
    total: int = 0
    error: str | None = None
    result: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "in_progress": self.in_progress,
            "status": self.status,
            "message": self.message,
            "current": self.current,
            "total": self.total,
            "percent": int(self.current * 100 / self.total) if self.total else 0,
            "error": self.error,
            "result": self.result,
        }


_status = MediaRefreshStatus()
_lock = Lock()


def get_status() -> dict:
    with _lock:
        return _status.to_dict()


def start_refresh(total: int) -> None:
    with _lock:
        _status.in_progress = True
        _status.status = "progress"
        _status.message = "Starting media server refresh..."
        _status.current = 0
        _status.total = total
        _status.error = None
        _status.result = []


def update_refresh(message: str, current: int | None = None) -> None:
    with _lock:
        _status.message = message
        if current is not None:
            _status.current = current


def complete_refresh(result: list[dict]) -> None:
    with _lock:
        _status.in_progress = False
        _status.status = "complete"
        _status.current = _status.total
        _status.message = "Media server refresh complete"
        _status.result = result


def fail_refresh(error: str) -> None:
    with _lock:
        _status.in_progress = False
        _status.status = "error"
        _status.message = f"Media server refresh failed: {error}"
        _status.error = error
