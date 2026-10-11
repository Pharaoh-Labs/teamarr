"""Per-device record of the channels Teamarr last pushed to Plex.

This is the ONLY thing that makes a channel removable. The channelmap PUT
replaces a device's whole state, so Teamarr has to decide what it may disable;
inferring that from a channel-number range claimed everything above
``channel_range_start``, which disabled other tools' channels and Teamarr's own
team channels on a default install. Recording what we actually pushed replaces
the guess: a channel absent from this table is never disabled by Teamarr.

Scope is ``(server_url, device_key, channel_profile_id)``. The profile belongs
in the key because a root-profile device (``/hdhr`` with no suffix) serves every
Dispatcharr profile, so it is normal to point several Teamarr server entries at
one device — with a device-only key they would each treat the others' channels
as their own stale ones and disable them on alternate runs.
"""

import json
from sqlite3 import Connection


def _scope(channel_profile_id: int | str | None) -> str:
    return "" if channel_profile_id is None else str(channel_profile_id)


def get_pushed_channels(
    conn: Connection,
    server_url: str,
    device_key: str,
    channel_profile_id: int | str | None,
) -> set[str]:
    """Channels this scope pushed on its last successful run (empty if never)."""
    row = conn.execute(
        """SELECT channel_keys FROM plex_pushed_channels
           WHERE server_url = ? AND device_key = ? AND channel_profile_id = ?""",
        (server_url, device_key, _scope(channel_profile_id)),
    ).fetchone()
    if not row or not row["channel_keys"]:
        return set()
    try:
        keys = json.loads(row["channel_keys"])
    except (TypeError, ValueError):
        return set()
    return {str(k) for k in keys} if isinstance(keys, list) else set()


def set_pushed_channels(
    conn: Connection,
    server_url: str,
    device_key: str,
    channel_profile_id: int | str | None,
    channel_keys: set[str],
) -> None:
    """Record what this scope just pushed. Call only after a verified write."""
    conn.execute(
        """INSERT INTO plex_pushed_channels
               (server_url, device_key, channel_profile_id, channel_keys, updated_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(server_url, device_key, channel_profile_id)
           DO UPDATE SET channel_keys = excluded.channel_keys,
                         updated_at = CURRENT_TIMESTAMP""",
        (
            server_url,
            device_key,
            _scope(channel_profile_id),
            json.dumps(sorted(channel_keys)),
        ),
    )
    conn.commit()
