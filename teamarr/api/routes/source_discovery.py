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
    TIER_NAME_ONLY,
    TIER_TEAMS,
    accept_candidate,
    discovery_status,
    fold_same_content,
    run_discovery_scan,
    suggestion_tier,
    team_stream_leagues,
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
    # Name of the M3U account the group comes from — the list is organized by it.
    m3u_account_name: str | None = None
    stream_count: int
    status: str
    tier: str | None  # 'games' | 'teams' | 'name_only' | None (not suggested)
    name_leagues: list[str]
    leagues: dict[str, int]
    team_leagues: dict[str, int]  # one-team matches in a league the name names
    events: int  # distinct events matched in the window
    best_game_matches: int
    days_matched: int
    scans: int
    last_seen_at: str | None
    last_matched_at: str | None
    # Another suggested group carrying the same events, when there is one with
    # more of them. Information only: this group is its own candidate.
    same_events_as: str | None = None


class CandidateListResponse(BaseModel):
    window_days: int
    candidates: list[CandidateResponse]
    scan: dict


def _account_names() -> dict[int, str]:
    """M3U account id -> name. Empty when Dispatcharr cannot be asked."""
    from teamarr.dispatcharr.factory import get_dispatcharr_connection

    try:
        dispatcharr = get_dispatcharr_connection(get_db)
        if not dispatcharr:
            return {}
        return {a.id: a.name for a in dispatcharr.m3u.list_accounts()}
    except Exception as e:
        logger.warning("[DISCOVERY] Failed to list M3U accounts: %s", e)
        return {}


def _to_response(
    candidate: CandidateEvidence, accounts: dict[int, str] | None = None
) -> CandidateResponse:
    names = [
        (accounts or {}).get(account_id) or f"Account {account_id}"
        for account_id in candidate.m3u_account_ids
    ]
    return CandidateResponse(
        m3u_account_name=", ".join(names) if names else None,
        id=candidate.id,
        m3u_group_id=candidate.m3u_group_id,
        m3u_group_name=candidate.m3u_group_name,
        m3u_account_ids=candidate.m3u_account_ids,
        stream_count=candidate.stream_count,
        status=candidate.status,
        tier=suggestion_tier(candidate),
        name_leagues=candidate.name_leagues,
        leagues=candidate.leagues,
        team_leagues=team_stream_leagues(candidate),
        events=len(candidate.event_ids),
        best_game_matches=candidate.best_game_matches,
        days_matched=candidate.days_matched,
        scans=candidate.scans,
        last_seen_at=candidate.last_seen_at,
        last_matched_at=candidate.last_matched_at,
    )


@router.get("/candidates", response_model=CandidateListResponse)
def list_candidates(include_dismissed: bool = False) -> CandidateListResponse:
    """Suggested sources, strongest evidence first.

    Only groups worth suggesting are returned: ones whose streams matched
    events in the evidence window, team-stream groups, then ones whose name
    alone names a subscribed league. Replay groups are never returned. The
    list is flat, ordered by M3U account; a group that carries the same events
    as a stronger one says so in ``same_events_as``.
    Dismissed groups are left out unless ``include_dismissed`` is set.
    """
    with get_db() as conn:
        candidates = get_candidates(conn, now_utc(), EVIDENCE_WINDOW_DAYS)
    shown = []
    for candidate in candidates:
        if candidate.status == "accepted":
            continue
        if candidate.status == "dismissed":
            if include_dismissed:
                shown.append(candidate)
        elif suggestion_tier(candidate) is not None:
            shown.append(candidate)

    accounts = _account_names()
    rows = []
    for primary, *others in fold_same_content([c for c in shown if c.status != "dismissed"]):
        rows.append(_to_response(primary, accounts))
        for other in others:
            row = _to_response(other, accounts)
            row.same_events_as = primary.m3u_group_name
            rows.append(row)
    rows.extend(_to_response(c, accounts) for c in shown if c.status == "dismissed")

    # Flat, by M3U account, strongest evidence first within each.
    tier_order = {TIER_GAMES: 0, TIER_TEAMS: 1, TIER_NAME_ONLY: 2}
    rows.sort(
        key=lambda r: (
            r.status == "dismissed",
            (r.m3u_account_name or "~").lower(),
            tier_order.get(r.tier or "", 3),
            -r.best_game_matches,
            r.m3u_group_name.lower(),
        )
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
