"""Typed contracts for the generation pipeline (#830, Packet 2).

Internal only. These types make the orchestration in ``generation.py``
explicit so it can be split into ordered stages without the phases
communicating through closure variables. They are deliberately **not** the
plugin ABI: a plugin boundary uses serialized records, not these classes.

Every type here is either moved verbatim from ``generation.py`` (``GenerationResult``,
``GenerationCancelled``) or additive. ``generation.py`` re-exports the moved
ones, so existing imports and monkeypatch paths keep working.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids import cycles
    from teamarr.consumers.event_group_processor.results import BatchProcessingResult
    from teamarr.consumers.team_processor import BatchTeamResult
    from teamarr.database.settings.types import (
        DispatcharrSettings,
        DisplaySettings,
        EPGSettings,
    )
    from teamarr.database.stats import ProcessingRun
    from teamarr.services import SportsDataService, TeamChannelManager


class GenerationCancelled(Exception):
    """Raised when a generation run is cancelled by the user."""


@dataclass
class GenerationResult:
    """Result of a full EPG generation run."""

    success: bool = True
    error: str | None = None

    # Timing
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_seconds: float = 0.0

    # EPG stats
    teams_processed: int = 0
    teams_programmes: int = 0
    groups_processed: int = 0
    groups_programmes: int = 0
    programmes_total: int = 0

    # File output
    file_written: bool = False
    file_path: str | None = None
    file_size: int = 0

    # Sub-task results
    m3u_refresh: dict = field(default_factory=dict)
    stream_ordering: dict = field(default_factory=dict)
    epg_refresh: dict = field(default_factory=dict)
    epg_association: dict = field(default_factory=dict)
    managed_team_channels: dict = field(default_factory=dict)
    managed_team_streams: dict = field(default_factory=dict)
    deletions: dict = field(default_factory=dict)
    reconciliation: dict = field(default_factory=dict)
    cleanup: dict = field(default_factory=dict)
    logo_cleanup: dict = field(default_factory=dict)
    channel_conflicts: dict = field(default_factory=dict)
    emby_refresh: dict = field(default_factory=dict)
    jellyfin_refresh: dict = field(default_factory=dict)
    channelsdvr_refresh: dict = field(default_factory=dict)
    channelsdvr_epg_refresh: dict = field(default_factory=dict)
    plex_refresh: dict = field(default_factory=dict)
    # One entry per media server refreshed this run (#649): persisted on the
    # run row so a server that fails every run is visible after the fact.
    media_server_outcomes: list[dict] = field(default_factory=list)

    # For stats run tracking
    run_id: int | None = None

    # Wall-clock seconds per generation phase (persisted to run stats so any
    # two runs — local or live — can be compared phase-by-phase).
    phase_timings: dict = field(default_factory=dict)


@dataclass(frozen=True)
class GenerationSettingsSnapshot:
    """The three settings groups generation reads together at run start.

    Deliberately not a snapshot of *every* setting. Reconciliation,
    media-server, stream-ordering and cleanup settings are read inside the
    phases that use them and have their own failure policies; hoisting them
    here would change when a bad value is noticed and which step it fails.
    """

    epg: EPGSettings
    dispatcharr: DispatcharrSettings
    display: DisplaySettings


@dataclass(frozen=True)
class ProgressUpdate:
    """One structured progress event.

    The field order matches the six positional arguments of the public
    ``ProgressCallback``, which is what ``legacy_progress_reporter`` adapts
    back to.
    """

    phase: str
    percent: int
    message: str
    current: int = 0
    total: int = 0
    item_name: str = ""


# The public callback shape, unchanged: callers (API, SSE, scheduler) pass one
# of these to run_full_generation() and must keep working untouched.
# (phase, percent, message, current, total, item_name) -> None
ProgressCallback = Callable[[str, int, str, int, int, str], None]

# The internal shape stages report through.
ProgressReporter = Callable[["ProgressUpdate"], None]


def legacy_progress_reporter(callback: ProgressCallback | None) -> ProgressReporter:
    """Adapt structured progress back to the six-argument public callback.

    A missing callback is a no-op, matching the existing ``update_progress``
    closure in the facade.
    """

    def report(update: ProgressUpdate) -> None:
        if callback is not None:
            callback(
                update.phase,
                update.percent,
                update.message,
                update.current,
                update.total,
                update.item_name,
            )

    return report


class CancellationToken(Protocol):
    """How a stage asks whether the user has cancelled."""

    def is_requested(self) -> bool:
        """Return whether cancellation has been requested, without raising."""
        ...

    def checkpoint(self) -> None:
        """Raise :class:`GenerationCancelled` if cancellation was requested."""
        ...


@dataclass(frozen=True)
class CallbackCancellationToken:
    """A token backed by a predicate — normally ``is_cancellation_requested``.

    The token never sets global terminal status. Persisting the cancelled run
    and calling ``generation_status.cancel_generation()`` stay the facade's
    outer exception handler's job, so a stage cannot half-finish a run.
    """

    requested: Callable[[], bool]

    def is_requested(self) -> bool:
        return self.requested()

    def checkpoint(self) -> None:
        if self.requested():
            raise GenerationCancelled("Cancelled by user")


@dataclass
class GenerationContext:
    """Everything one generation run needs, and everything its stages share.

    Explicit fields rather than an open-ended dictionary: a stage that reads
    something no earlier stage wrote is then a type error, not a KeyError at
    99% progress. Fields below the divider are *produced* during the run —
    each is written by one stage and read by a later one.
    """

    db_factory: Callable[[], Any]
    dispatcharr_client: Any | None
    manual: bool
    settings: GenerationSettingsSnapshot
    sports_service: SportsDataService
    progress: ProgressReporter
    cancellation: CancellationToken
    result: GenerationResult
    stats_run: ProcessingRun
    current_generation: int

    # ---- produced during the run -------------------------------------
    team_result: BatchTeamResult | None = None
    group_result: BatchProcessingResult | None = None
    external_occupied: set[int] = field(default_factory=set)
    lifecycle_service: Any | None = None
    media_jobs: list[tuple[str, Any]] = field(default_factory=list)
    channels_deleted_count: int = 0

    # Persistent managed team channels (#826). The manager is built in an
    # untimed stage after team processing; the matched streams and completed
    # group ids are collected during group processing; all three are consumed
    # by the team-channel sync stage, and the manager again by EPG association.
    team_channel_manager: TeamChannelManager | None = None
    team_matched_streams: list[dict] = field(default_factory=list)
    team_completed_groups: set[int] = field(default_factory=set)
    # Whether global channel reassignment performed a full re-layout (#810).
    # Written by the reassignment stage, read by the very next one.
    relayout: bool = False

    def report(
        self,
        phase: str,
        percent: int,
        message: str,
        current: int = 0,
        total: int = 0,
        item_name: str = "",
    ) -> None:
        """Convenience wrapper so a stage can emit progress positionally."""
        self.progress(
            ProgressUpdate(
                phase=phase,
                percent=percent,
                message=message,
                current=current,
                total=total,
                item_name=item_name,
            )
        )

    def checkpoint(self) -> None:
        """Raise if the user has cancelled. See :class:`CancellationToken`."""
        self.cancellation.checkpoint()


__all__: Sequence[str] = [
    "CallbackCancellationToken",
    "CancellationToken",
    "GenerationCancelled",
    "GenerationContext",
    "GenerationResult",
    "GenerationSettingsSnapshot",
    "ProgressCallback",
    "ProgressReporter",
    "ProgressUpdate",
    "legacy_progress_reporter",
]
