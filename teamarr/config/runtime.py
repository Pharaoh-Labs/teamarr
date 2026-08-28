"""Runtime safety flags (#554): ``SCHEDULER`` and ``DRY_RUN``.

Teamarr's in-process scheduler has real-world side effects — it writes
channels into Dispatcharr and pushes guide refreshes to Emby / Jellyfin /
Channels DVR. Two live instances (a dev box next to prod) double-fire. These
two **environment-only** flags make a second instance safe:

- ``SCHEDULER=off`` — the API and UI start, but the cron scheduler never
  does. Nothing fires on a timer. Manual, user-initiated generation still
  works: the operator is explicitly asking for it.
- ``DRY_RUN=true`` — every outbound write is resolved and logged, never
  executed: Dispatcharr POST/PATCH/DELETE are suppressed at the client
  (``DispatcharrClient.request``), and media-server guide refreshes are
  skipped in generation. Reads are unaffected, so the full generation path
  can be exercised against real data.

Env-only by design: dev databases are snapshotted from prod, so a DB-backed
flag would either leak into prod or be overwritten by the next snapshot.
Both flags are surfaced on ``GET /health`` (``runtime``) and as a banner in
the UI so that "nothing is being written" is never silent.
"""

import os

_OFF = {"off", "0", "false", "no", "disabled"}
_ON = {"on", "1", "true", "yes", "enabled"}


def scheduler_enabled() -> bool:
    """False when ``SCHEDULER`` is set to an off-value (``off``/``0``/``false``/``no``).

    Read at call time (not import time) so tests can set the environment, and
    so the value reflects the process that actually started.
    """
    return os.getenv("SCHEDULER", "on").strip().lower() not in _OFF


def dry_run() -> bool:
    """True when ``DRY_RUN`` is set to an on-value (``true``/``1``/``yes``/``on``)."""
    return os.getenv("DRY_RUN", "").strip().lower() in _ON


def runtime_flags() -> dict[str, bool]:
    """The flags as reported on ``/health`` and read by the UI banner."""
    return {"scheduler_enabled": scheduler_enabled(), "dry_run": dry_run()}
