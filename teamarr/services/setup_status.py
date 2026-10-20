"""Getting Started checklist state (#818, epic 297x).

One read of the facts a new install needs to see in order: is Dispatcharr
connected, is there a source, a subscription, did streams match, did a run
complete, did it create channels. The Dashboard card renders these as six
rows and goes away on its own once the install is working.

Dispatcharr is assumed (step 0). It is technically optional, but the whole
channel-management side of Teamarr is built on it, and a first-run guide
that branched for the XMLTV-only route would be guiding almost nobody.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from sqlite3 import Connection


@dataclass(frozen=True)
class SetupStatus:
    """What the checklist knows. Labels and links live in the frontend."""

    dispatcharr_configured: bool
    dispatcharr_connected: bool
    sources: int
    leagues: int
    streams_matched: int  # last completed run
    runs_completed: int
    channels_active: int
    dismissed: bool

    @property
    def complete(self) -> bool:
        """Done means a run has completed and channels exist — not page visits."""
        return self.runs_completed > 0 and self.channels_active > 0

    @property
    def visible(self) -> bool:
        return not self.dismissed and not self.complete

    def to_dict(self) -> dict:
        data = asdict(self)
        data["complete"] = self.complete
        data["visible"] = self.visible
        return data


def compute_setup_status(
    conn: Connection,
    probe: Callable[[], tuple[bool, bool]],
) -> SetupStatus:
    """Read the checklist facts from one connection.

    ``probe`` answers ``(configured, connected)`` for Dispatcharr; the route
    passes the memoised ``DispatcharrFactory.probe_connection`` so a dashboard
    poll never costs a fresh login. Tests pass a stub.
    """
    from teamarr.database.settings import get_all_settings
    from teamarr.database.subscription import get_subscription

    configured, connected = probe()
    sources = conn.execute(
        "SELECT COUNT(*) FROM event_epg_groups WHERE enabled = 1 AND is_channel_source = 0"
    ).fetchone()[0]
    leagues = len(get_subscription(conn).leagues)
    runs_completed = conn.execute(
        "SELECT COUNT(*) FROM processing_runs WHERE run_type = 'full_epg' "
        "AND status IN ('completed', 'partial')"
    ).fetchone()[0]
    last = conn.execute(
        "SELECT streams_matched FROM processing_runs WHERE run_type = 'full_epg' "
        "AND status IN ('completed', 'partial') ORDER BY started_at DESC, id DESC LIMIT 1"
    ).fetchone()
    # Event channels and team channels both count: a team-only install is set
    # up the moment its first team channel exists in Dispatcharr.
    channels_active = (
        conn.execute("SELECT COUNT(*) FROM managed_channels WHERE deleted_at IS NULL").fetchone()[0]
        + conn.execute(
            "SELECT COUNT(*) FROM managed_team_channels WHERE dispatcharr_channel_id IS NOT NULL"
        ).fetchone()[0]
    )
    dismissed = get_all_settings(conn).display.getting_started_dismissed
    return SetupStatus(
        dispatcharr_configured=configured,
        dispatcharr_connected=connected,
        sources=sources,
        leagues=leagues,
        streams_matched=int(last[0] or 0) if last else 0,
        runs_completed=runs_completed,
        channels_active=channels_active,
        dismissed=bool(dismissed),
    )
