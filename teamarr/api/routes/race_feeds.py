"""Race feeds API (#245): per-league driver and feed-variant rows on the keyword engine.

Each row is a league-scoped exception keyword the roster refresh maintains;
the user owns only ``behavior`` and ``enabled``. See ``database/race_feeds.py``.
"""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from teamarr.database import get_db
from teamarr.database.race_feeds import (
    RaceFeed,
    get_race_feed,
    list_race_feeds,
    race_feed_leagues,
    set_behavior_for_kind,
    update_race_feed,
)

logger = logging.getLogger(__name__)
router = APIRouter()

FeedBehavior = Literal["consolidate", "separate", "ignore"]
FeedKind = Literal["driver", "variant"]


class RaceFeedResponse(BaseModel):
    id: int
    league: str
    feed_key: str
    kind: str
    label: str
    match_terms: str
    match_term_list: list[str]
    behavior: str
    enabled: bool
    managed: bool
    last_seen: str | None = None


class RaceFeedListResponse(BaseModel):
    league: str | None
    leagues: list[str]
    feeds: list[RaceFeedResponse]
    total: int


class RaceFeedUpdate(BaseModel):
    behavior: FeedBehavior | None = None
    enabled: bool | None = None


class RaceFeedBulkUpdate(BaseModel):
    league: str
    kind: FeedKind
    behavior: FeedBehavior


def _to_response(feed: RaceFeed) -> RaceFeedResponse:
    return RaceFeedResponse(
        id=feed.id or 0,
        league=feed.league,
        feed_key=feed.feed_key,
        kind=feed.kind,
        label=feed.label,
        match_terms=feed.match_terms,
        match_term_list=feed.match_term_list,
        behavior=feed.behavior,
        enabled=feed.enabled,
        managed=feed.managed,
        last_seen=feed.last_seen.isoformat() if feed.last_seen else None,
    )


@router.get("", response_model=RaceFeedListResponse)
def list_feeds(league: str | None = Query(None, description="League code, e.g. f1")):
    """List race feeds, optionally for one league. Drivers first, then variants."""
    with get_db() as conn:
        feeds = list_race_feeds(conn, league)
        leagues = race_feed_leagues(conn)
    return RaceFeedListResponse(
        league=league,
        leagues=leagues,
        feeds=[_to_response(f) for f in feeds],
        total=len(feeds),
    )


@router.patch("/{feed_id}", response_model=RaceFeedResponse)
def patch_feed(feed_id: int, request: RaceFeedUpdate):
    """Change a feed's behavior and/or enabled flag (the user-owned fields)."""
    with get_db() as conn:
        if get_race_feed(conn, feed_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Race feed not found")
        feed = update_race_feed(conn, feed_id, behavior=request.behavior, enabled=request.enabled)
    assert feed is not None
    return _to_response(feed)


@router.post("/bulk", response_model=RaceFeedListResponse)
def bulk_behavior(request: RaceFeedBulkUpdate):
    """Set one behavior on every driver (or every variant) row of a league."""
    with get_db() as conn:
        set_behavior_for_kind(conn, request.league, request.kind, request.behavior)
        feeds = list_race_feeds(conn, request.league)
        leagues = race_feed_leagues(conn)
    return RaceFeedListResponse(
        league=request.league,
        leagues=leagues,
        feeds=[_to_response(f) for f in feeds],
        total=len(feeds),
    )


@router.post("/refresh", response_model=RaceFeedListResponse)
def refresh_feeds(league: str | None = Query(None, description="League code; omit for all")):
    """Re-harvest the roster now (also runs with every cache refresh)."""
    from teamarr.consumers.cache.refresh import CacheRefresher

    results = CacheRefresher().refresh_race_feeds(only_league=league)
    logger.info("[RACE_FEEDS] Manual refresh: %s", results)
    with get_db() as conn:
        feeds = list_race_feeds(conn, league)
        leagues = race_feed_leagues(conn)
    return RaceFeedListResponse(
        league=league, leagues=leagues, feeds=[_to_response(f) for f in feeds], total=len(feeds)
    )
