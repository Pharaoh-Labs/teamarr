"""Numbering exceptions (pinned channel-number blocks, #333) endpoints.

CRUD over ``numbering_exceptions`` plus a reorder endpoint (UI drag order is
the within-level tie-break) and an effective-layout preview that shows where
today's channels would land under the current blocks.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from teamarr.database import get_db
from teamarr.database.numbering_exceptions import (
    add_numbering_exception,
    delete_numbering_exception,
    get_numbering_exceptions,
    reorder_numbering_exceptions,
    update_numbering_exception,
)

router = APIRouter(prefix="/numbering-exceptions", tags=["Numbering Exceptions"])


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class NumberingExceptionModel(BaseModel):
    """One pinned block."""

    id: int
    scope: str  # 'team' | 'league' | 'sport'
    sport: str
    league_code: str | None = None
    team_name: str | None = None
    provider: str | None = None
    provider_team_id: str | None = None
    start: int
    end: int | None = None
    label: str | None = None
    sort_order: int = 0
    enabled: bool = True
    display_name: str | None = None
    channel_count: int = 0


class NumberingExceptionCreate(BaseModel):
    """Create a pinned block.

    - team:   provider + team_id (a TeamPicker entry; name/sport resolved from team_cache)
    - league: league_code (sport resolved from leagues)
    - sport:  sport
    """

    scope: str
    start: int = Field(ge=1)
    end: int | None = Field(default=None, ge=1)
    label: str | None = None
    sport: str | None = None
    league_code: str | None = None
    provider: str | None = None
    team_id: str | None = None
    team_league: str | None = None


class NumberingExceptionUpdate(BaseModel):
    """Update a block's range / label / enabled flag (scope is immutable)."""

    start: int | None = Field(default=None, ge=1)
    end: int | None = Field(default=None, ge=1)
    clear_end: bool = False
    label: str | None = None
    clear_label: bool = False
    enabled: bool | None = None


class NumberingExceptionReorder(BaseModel):
    ordered_ids: list[int]


class LanePreviewModel(BaseModel):
    """Where a lane's current channels would land."""

    id: int | None  # None = default range
    label: str
    start: int
    end: int | None = None
    channel_count: int
    first_number: int | None = None
    last_number: int | None = None
    spills_into_next: bool = False


# =============================================================================
# HELPERS
# =============================================================================


def _display_name(conn, exc) -> str:
    if exc.scope == "team":
        return exc.team_name or "?"
    if exc.scope == "league":
        row = conn.execute(
            "SELECT display_name FROM leagues WHERE league_code = ?", (exc.league_code,)
        ).fetchone()
        return (row["display_name"] if row and row["display_name"] else exc.league_code) or "?"
    from teamarr.core.sports import get_sport_display_names_from_db

    names = get_sport_display_names_from_db(conn)
    return names.get(exc.sport) or exc.sport.title()


def _with_counts(conn, exceptions) -> list[NumberingExceptionModel]:
    """Attach display names and how many active channels each block currently owns."""
    from teamarr.database.channel_numbers import _default_lane, get_all_channels_sorted
    from teamarr.database.numbering_exceptions import LaneResolver

    resolver = LaneResolver.load(conn, _default_lane(conn))
    counts: dict[int | None, int] = {}
    for ch in get_all_channels_sorted(conn):
        lane = resolver.resolve(
            ch.get("sport"), ch.get("league"), ch.get("home_team"), ch.get("away_team")
        )
        counts[lane.id] = counts.get(lane.id, 0) + 1
    # Group members share a lane id (the lowest id at that start); count per row by start.
    start_counts: dict[int, int] = {}
    for exc in exceptions:
        lane = resolver.lane_for(exc)
        start_counts[exc.start] = counts.get(lane.id, 0)
    return [
        NumberingExceptionModel(
            **{k: v for k, v in exc.__dict__.items() if k not in ("created_at", "updated_at")},
            display_name=_display_name(conn, exc),
            channel_count=start_counts.get(exc.start, 0),
        )
        for exc in exceptions
    ]


# =============================================================================
# ENDPOINTS
# =============================================================================


@router.get("", response_model=list[NumberingExceptionModel])
def list_numbering_exceptions():
    """List pinned blocks in precedence order (drag order)."""
    with get_db() as conn:
        return _with_counts(conn, get_numbering_exceptions(conn))


@router.post("", response_model=NumberingExceptionModel)
def create_numbering_exception(data: NumberingExceptionCreate):
    """Add a pinned block."""
    with get_db() as conn:
        created = add_numbering_exception(
            conn,
            scope=data.scope,
            start=data.start,
            end=data.end,
            label=data.label,
            sport=data.sport,
            league_code=data.league_code,
            provider=data.provider,
            provider_team_id=data.team_id,
            team_league=data.team_league,
        )
        if created is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Could not add block — check scope, start/end, "
                    "and that the team/league exists"
                ),
            )
        return _with_counts(conn, [created])[0]


@router.put("/reorder")
def reorder(data: NumberingExceptionReorder):
    """Persist drag order (the tie-break within a precedence level)."""
    with get_db() as conn:
        reorder_numbering_exceptions(conn, data.ordered_ids)
    return {"success": True}


@router.get("/preview", response_model=list[LanePreviewModel])
def preview_layout():
    """Effective layout: how many of today's channels each lane would hold and
    the number span they'd occupy in compact placement (a spill indicator)."""
    from teamarr.database.channel_numbers import _default_lane, get_all_channels_sorted
    from teamarr.database.numbering_exceptions import LaneResolver

    with get_db() as conn:
        resolver = LaneResolver.load(conn, _default_lane(conn))
        lanes = resolver.lanes()
        buckets: dict[int | None, list[dict]] = {lane.id: [] for lane in lanes}
        for ch in get_all_channels_sorted(conn):
            lane = resolver.resolve(
                ch.get("sport"), ch.get("league"), ch.get("home_team"), ch.get("away_team")
            )
            buckets[lane.id].append(ch)
        exceptions = {e.id: e for e in get_numbering_exceptions(conn)}

        out: list[LanePreviewModel] = []
        for i, lane in enumerate(lanes):
            n = len(buckets[lane.id])
            if lane.is_default:
                label = "Everything else"
            else:
                exc = exceptions.get(lane.id) if lane.id is not None else None
                members = [
                    _display_name(conn, e) for e in exceptions.values() if e.start == lane.start
                ]
                label = (exc.label if exc and exc.label else "") or " · ".join(members)
                if exc and exc.label and members:
                    label = f"{exc.label}: {' · '.join(members)}"
            first = lane.start if n else None
            last = lane.start + n - 1 if n else None
            next_start = lanes[i + 1].start if i + 1 < len(lanes) else None
            spills = bool(last is not None and next_start is not None and last >= next_start)
            if lane.end is not None and last is not None and last > lane.end:
                spills = True
            out.append(
                LanePreviewModel(
                    id=lane.id, label=label, start=lane.start, end=lane.end,
                    channel_count=n, first_number=first, last_number=last,
                    spills_into_next=spills,
                )
            )
        return out


@router.put("/{exception_id}", response_model=NumberingExceptionModel)
def update(exception_id: int, data: NumberingExceptionUpdate):
    """Update a block's start / end / label / enabled."""
    with get_db() as conn:
        updated = update_numbering_exception(
            conn,
            exception_id,
            start=data.start,
            end=None if data.clear_end else (data.end if data.end is not None else ...),
            label=None if data.clear_label else (data.label if data.label is not None else ...),
            enabled=data.enabled,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Block not found or invalid range",
            )
        return _with_counts(conn, [updated])[0]


@router.delete("/{exception_id}")
def delete(exception_id: int):
    """Remove a pinned block."""
    with get_db() as conn:
        removed = delete_numbering_exception(conn, exception_id)
    return {"success": removed, "id": exception_id}
