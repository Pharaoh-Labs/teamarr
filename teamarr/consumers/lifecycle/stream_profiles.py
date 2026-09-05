"""Resolve channel-source stream-profile overrides."""

from sqlite3 import Connection

from teamarr.database.channels import get_channel_streams
from teamarr.database.settings import get_epg_settings

from .timing import is_stream_in_window


def resolve_stream_profile_for_group(
    conn: Connection,
    default_stream_profile_id: int | None,
    dispatcharr_channel_group_id: int | None,
) -> int | None:
    """Return an explicit channel-source group override or the global default."""
    if dispatcharr_channel_group_id is None:
        return default_stream_profile_id
    for mapping in get_epg_settings(conn).stream_profile_overrides:
        if (
            mapping.get("target_type") == "dispatcharr_channel_group"
            and mapping.get("target_id") == dispatcharr_channel_group_id
        ):
            return mapping.get("stream_profile_id")
    return default_stream_profile_id


def resolve_channel_stream_profile(
    conn: Connection,
    managed_channel_id: int,
    default_stream_profile_id: int | None,
) -> int | None:
    """Return the top active ordered stream's override or the global default."""
    for stream in get_channel_streams(conn, managed_channel_id):
        if is_stream_in_window(stream.attach_at, stream.detach_at):
            return resolve_stream_profile_for_group(
                conn, default_stream_profile_id, stream.dispatcharr_channel_group_id
            )
    return default_stream_profile_id
