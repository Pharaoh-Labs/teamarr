"""Startup state management for tracking application initialization."""

import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum


class StartupPhase(StrEnum):
    """Phases of application startup."""

    INITIALIZING = "initializing"
    LOADING_SETTINGS = "loading_settings"
    CONNECTING_DISPATCHARR = "connecting_dispatcharr"
    STARTING_SCHEDULER = "starting_scheduler"
    READY = "ready"


# Human-readable descriptions for each phase
PHASE_DESCRIPTIONS = {
    StartupPhase.INITIALIZING: "Initializing database...",
    StartupPhase.LOADING_SETTINGS: "Loading settings...",
    StartupPhase.CONNECTING_DISPATCHARR: "Connecting to Dispatcharr...",
    StartupPhase.STARTING_SCHEDULER: "Starting scheduler...",
    StartupPhase.READY: "Ready",
}


@dataclass
class StartupState:
    """Tracks the current startup state of the application."""

    phase: StartupPhase = StartupPhase.INITIALIZING
    message: str = "Starting up..."
    started_at: datetime = field(default_factory=datetime.now)
    ready_at: datetime | None = None
    error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def set_phase(self, phase: StartupPhase, message: str | None = None) -> None:
        """Update the current startup phase."""
        with self._lock:
            self.phase = phase
            self.message = message or PHASE_DESCRIPTIONS.get(phase, str(phase))
            if phase == StartupPhase.READY:
                self.ready_at = datetime.now()

    def set_error(self, error: str) -> None:
        """Set an error state."""
        with self._lock:
            self.error = error

    @property
    def is_ready(self) -> bool:
        """Check if startup is complete."""
        return self.phase == StartupPhase.READY

    @property
    def elapsed_seconds(self) -> float:
        """Get elapsed time since startup began."""
        end = self.ready_at or datetime.now()
        return (end - self.started_at).total_seconds()

    def to_dict(self) -> dict:
        """Convert to dictionary for API response."""
        with self._lock:
            return {
                "phase": self.phase.value,
                "message": self.message,
                "is_ready": self.is_ready,
                "elapsed_seconds": round(self.elapsed_seconds, 1),
                "error": self.error,
            }


# Global startup state instance
_startup_state = StartupState()


def get_startup_state() -> StartupState:
    """Get the global startup state instance."""
    return _startup_state


def reset_startup_state() -> None:
    """Reset startup state (for testing)."""
    global _startup_state
    _startup_state = StartupState()
