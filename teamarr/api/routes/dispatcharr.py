"""Dispatcharr integration API endpoints.

Provides endpoints for:
- Testing Dispatcharr connection
- Listing M3U accounts and groups
- Fetching streams for preview
"""

import logging

from fastapi import APIRouter, HTTPException

from teamarr.consumers.event_group_processor.stream_fetcher import managed_channel_ids
from teamarr.database import get_db
from teamarr.dispatcharr.factory import get_dispatcharr_connection
from teamarr.utilities.sorting import natural_sort_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dispatcharr")


@router.get("/m3u-accounts")
def list_m3u_accounts() -> list[dict]:
    """List all M3U accounts from Dispatcharr.

    Returns:
        List of M3U accounts with id, name, and metadata
    """
    conn = get_dispatcharr_connection(db_factory=get_db)
    if not conn:
        raise HTTPException(status_code=503, detail="Dispatcharr not configured or unavailable")

    accounts = conn.m3u.list_accounts(include_custom=False)
    return [
        {
            "id": a.id,
            "name": a.name,
            "url": a.url,
            "status": a.status,
            "updated_at": a.updated_at,
        }
        for a in accounts
    ]


@router.get("/m3u-accounts/{account_id}/groups")
def list_m3u_groups(account_id: int) -> list[dict]:
    """List M3U groups (channel groups) for a specific account.

    Args:
        account_id: M3U account ID

    Returns:
        List of channel groups with stream counts
    """
    conn = get_dispatcharr_connection(db_factory=get_db)
    if not conn:
        raise HTTPException(status_code=503, detail="Dispatcharr not configured or unavailable")

    # The account detail endpoint carries per-group stream counts, so this is
    # two requests total instead of one stream listing per group (issue #265)
    names_by_id = {g.id: g.name for g in conn.m3u.list_groups()}
    counts = conn.m3u.get_account_group_counts(account_id)

    return [
        {
            "id": group_id,
            "name": names_by_id[group_id],
            "stream_count": count,
        }
        for group_id, count in counts.items()
        if count > 0 and group_id in names_by_id
    ]



@router.get("/m3u-accounts/{account_id}/groups/{group_id}/streams")
def list_group_streams(account_id: int, group_id: int) -> list[dict]:
    """List streams in a specific M3U group.

    Args:
        account_id: M3U account ID
        group_id: Channel group ID

    Returns:
        List of streams with id and name, sorted naturally
    """
    conn = get_dispatcharr_connection(db_factory=get_db)
    if not conn:
        raise HTTPException(status_code=503, detail="Dispatcharr not configured or unavailable")

    streams = conn.m3u.list_streams(group_id=group_id, account_id=account_id, limit=500)

    # Sort using natural ordering (ESPN+ 2 before ESPN+ 10)
    return sorted(
        [
            {
                "id": s.id,
                "name": s.name,
            }
            for s in streams
        ],
        key=lambda x: natural_sort_key(x["name"]),
    )


@router.get("/channel-groups")
def list_channel_groups(exclude_m3u: bool = True, with_channels: bool = False) -> list[dict]:
    """List Dispatcharr channel groups (for channel assignment).

    Args:
        exclude_m3u: If True, exclude groups originating from M3U accounts.
                     Defaults to True since M3U groups shouldn't be used for channel assignment.
        with_channels: If True, return ONLY groups that hold at least one
                       non-Teamarr channel, each with a ``channel_count``, and
                       ignore ``exclude_m3u`` entirely (#631). Dispatcharr uses
                       one group table for stream and channel organization, and
                       ``m3u_accounts`` does not separate them — it is set for
                       any group name a playlist carries, so it silently hides
                       groups the user curated channels into. "Holds channels"
                       is the honest test for the channel-source picker, whose
                       scan scopes on the channel's own ``channel_group_id``.

    Returns:
        List of channel groups
    """
    conn = get_dispatcharr_connection(db_factory=get_db)
    if not conn:
        raise HTTPException(status_code=503, detail="Dispatcharr not configured or unavailable")

    if with_channels:
        # Teamarr's own channels are OUTPUT, never a source: a group holding
        # only Teamarr channels must read as empty, matching the scan.
        counts = conn.channels.count_channels_by_group(
            exclude_channel_ids=managed_channel_ids(get_db)
        )
        return [
            {
                "id": g.id,
                "name": g.name,
                "from_m3u": bool(g.m3u_accounts),
                "channel_count": counts[g.id],
            }
            for g in conn.m3u.list_groups()
            if counts.get(g.id)
        ]

    groups = conn.m3u.list_groups(exclude_m3u=exclude_m3u)
    return [
        {
            "id": g.id,
            "name": g.name,
            "from_m3u": bool(g.m3u_accounts),
        }
        for g in groups
    ]


@router.post("/channel-groups")
def create_channel_group(name: str) -> dict:
    """Create a new channel group in Dispatcharr.

    Args:
        name: Group name

    Returns:
        Created group data
    """
    conn = get_dispatcharr_connection(db_factory=get_db)
    if not conn:
        raise HTTPException(status_code=503, detail="Dispatcharr not configured or unavailable")

    result = conn.m3u.create_channel_group(name)
    if not result.success:
        logger.warning("[FAILED] Create channel group name=%s error=%s", name, result.error)
        raise HTTPException(status_code=400, detail=result.error)

    logger.info("[CREATED] Channel group in Dispatcharr name=%s", name)
    assert result.data is not None  # success guaranteed non-None data above
    return result.data


@router.get("/channel-profiles")
def list_channel_profiles() -> list[dict]:
    """List all channel profiles from Dispatcharr.

    Returns:
        List of channel profiles
    """
    conn = get_dispatcharr_connection(db_factory=get_db)
    if not conn:
        raise HTTPException(status_code=503, detail="Dispatcharr not configured or unavailable")

    profiles = conn.channels.list_profiles()
    return [
        {
            "id": p.id,
            "name": p.name,
        }
        for p in profiles
    ]


@router.post("/channel-profiles")
def create_channel_profile(name: str) -> dict:
    """Create a new channel profile in Dispatcharr.

    Args:
        name: Profile name

    Returns:
        Created profile data
    """
    conn = get_dispatcharr_connection(db_factory=get_db)
    if not conn:
        raise HTTPException(status_code=503, detail="Dispatcharr not configured or unavailable")

    result = conn.channels.create_profile(name)
    if not result.success:
        logger.warning("[FAILED] Create channel profile name=%s error=%s", name, result.error)
        raise HTTPException(status_code=400, detail=result.error)

    logger.info("[CREATED] Channel profile in Dispatcharr name=%s", name)
    assert result.data is not None  # success guaranteed non-None data above
    return result.data


@router.get("/stream-profiles")
def list_stream_profiles() -> list[dict]:
    """List all stream profiles from Dispatcharr.

    Stream profiles define how streams are processed (ffmpeg, VLC, proxy, etc).

    Returns:
        List of active stream profiles
    """
    conn = get_dispatcharr_connection(db_factory=get_db)
    if not conn:
        raise HTTPException(status_code=503, detail="Dispatcharr not configured or unavailable")

    profiles = conn.channels.list_stream_profiles()
    return [
        {
            "id": p.id,
            "name": p.name,
            "command": p.command,
        }
        for p in profiles
    ]


