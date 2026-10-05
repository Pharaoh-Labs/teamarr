"""Source discovery API (#997): suggested sources and the scan that finds them.

A candidate is an M3U group that is not a source. See
``consumers/source_discovery.py`` for how evidence is gathered and judged.
"""

from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from teamarr.consumers.source_discovery import (
    EVIDENCE_WINDOW_DAYS,
    TIER_GAMES,
    accept_candidate,
    discovery_status,
    run_discovery_scan,
    suggestion_tier,
)
from teamarr.database import get_db
from teamarr.database.source_candidates import (
    CandidateEvidence,
    get_candidates,
    set_candidate_status,
)
from teamarr.utilities.tz import now_utc

logger = logging.getLogger(__name__)
router = APIRouter()


class CandidateResponse(BaseModel):
    id: int
    m3u_group_id: int
    m3u_group_name: str
    m3u_account_ids: list[int]
    stream_count: int
    status: str
    tier: str | None  # 'games' | 'name_only' | None (not suggested)
    name_leagues: list[str]
    leagues: dict[str, int]
    best_game_matches: int
    days_matched: int
    scans: int
    last_seen_at: str | None
    last_matched_at: str | None


class CandidateListResponse(BaseModel):
    window_days: int
    candidates: list[CandidateResponse]
    scan: dict


def _to_response(candidate: CandidateEvidence) -> CandidateResponse:
    return CandidateResponse(
        id=candidate.id,
        m3u_group_id=candidate.m3u_group_id,
        m3u_group_name=candidate.m3u_group_name,
        m3u_account_ids=candidate.m3u_account_ids,
        stream_count=candidate.stream_count,
        status=candidate.status,
        tier=suggestion_tier(candidate),
        name_leagues=candidate.name_leagues,
        leagues=candidate.leagues,
        best_game_matches=candidate.best_game_matches,
        days_matched=candidate.days_matched,
        scans=candidate.scans,
        last_seen_at=candidate.last_seen_at,
        last_matched_at=candidate.last_matched_at,
    )


@router.get("/candidates", response_model=CandidateListResponse)
def list_candidates(include_dismissed: bool = False) -> CandidateListResponse:
    """Suggested sources, strongest evidence first.

    Only groups worth suggesting are returned: ones with game matches in the
    evidence window, then ones whose name alone names a subscribed league.
    Dismissed groups are left out unless ``include_dismissed`` is set.
    """
    with get_db() as conn:
        candidates = get_candidates(conn, now_utc(), EVIDENCE_WINDOW_DAYS)
    rows = []
    for candidate in candidates:
        if candidate.status == "accepted":
            continue
        if candidate.status == "dismissed" and not include_dismissed:
            continue
        row = _to_response(candidate)
        if row.tier is not None or candidate.status == "dismissed":
            rows.append(row)
    rows.sort(
        key=lambda r: (r.tier != TIER_GAMES, -r.best_game_matches, r.m3u_group_name.lower())
    )
    return CandidateListResponse(
        window_days=EVIDENCE_WINDOW_DAYS, candidates=rows, scan=discovery_status()
    )


@router.post("/scan", status_code=status.HTTP_202_ACCEPTED)
def start_scan() -> dict:
    """Start a discovery scan in the background. 409 when one is already running."""
    if discovery_status()["running"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "A discovery scan is already running")
    threading.Thread(
        target=run_discovery_scan, args=(get_db,), name="source-discovery", daemon=True
    ).start()
    return {"started": True}


@router.get("/status")
def get_status() -> dict:
    """Whether a scan is running, its progress, and the last scan's summary."""
    return discovery_status()


def _set_status(candidate_id: int, new_status: str) -> dict:
    with get_db() as conn:
        if not set_candidate_status(conn, candidate_id, new_status):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
    return {"id": candidate_id, "status": new_status}


@router.post("/candidates/{candidate_id}/dismiss")
def dismiss_candidate(candidate_id: int) -> dict:
    """Dismiss a candidate. It is not suggested or scanned again until restored."""
    return _set_status(candidate_id, "dismissed")


@router.post("/candidates/{candidate_id}/restore")
def restore_candidate(candidate_id: int) -> dict:
    """Undo a dismissal."""
    return _set_status(candidate_id, "new")


@router.post("/candidates/{candidate_id}/accept", status_code=status.HTTP_201_CREATED)
def accept(candidate_id: int) -> dict:
    """Create a managed source from a candidate.

    A managed source is disabled when it matches nothing for two weeks and
    re-enabled when its group carries games again; editing it by hand makes
    it an ordinary source that is never touched.
    """
    with get_db() as conn:
        candidates = {c.id: c for c in get_candidates(conn, now_utc(), EVIDENCE_WINDOW_DAYS)}
        candidate = candidates.get(candidate_id)
        if candidate is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Candidate not found")
        if candidate.status == "accepted":
            raise HTTPException(status.HTTP_409_CONFLICT, "Candidate is already a source")
        source_id = accept_candidate(conn, candidate)
    return {"id": candidate_id, "status": "accepted", "source_group_id": source_id}
