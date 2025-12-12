"""EPG generation endpoints."""

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response

from teamarr.api.dependencies import get_sports_service
from teamarr.api.models import (
    EPGGenerateRequest,
    EPGGenerateResponse,
    EventEPGRequest,
    EventMatchRequest,
    EventMatchResponse,
)
from teamarr.consumers import (
    EventEPGOptions,
    EventMatcher,
    Orchestrator,
    TeamConfig,
    TeamEPGOptions,
)
from teamarr.database import get_db
from teamarr.services import SportsDataService

router = APIRouter()


# =============================================================================
# Team-based EPG endpoints
# =============================================================================


def _load_team_configs(team_ids: list[int] | None = None) -> list[TeamConfig]:
    """Load team configs from database."""
    with get_db() as conn:
        if team_ids:
            placeholders = ",".join("?" * len(team_ids))
            cursor = conn.execute(
                f"SELECT * FROM teams WHERE id IN ({placeholders}) AND active = 1",
                team_ids,
            )
        else:
            cursor = conn.execute("SELECT * FROM teams WHERE active = 1")

        configs = []
        for row in cursor.fetchall():
            configs.append(
                TeamConfig(
                    team_id=row["provider_team_id"],
                    league=row["league"],
                    team_name=row["team_name"],
                    channel_id=row["channel_id"],
                    logo_url=row["channel_logo_url"] or row["team_logo_url"],
                )
            )
        return configs


def _parse_team_ids(team_ids: str | None) -> list[int] | None:
    """Parse comma-separated team IDs."""
    if not team_ids:
        return None
    try:
        return [int(x.strip()) for x in team_ids.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="team_ids must be comma-separated integers",
        ) from None


@router.post("/epg/generate", response_model=EPGGenerateResponse)
def generate_epg(
    request: EPGGenerateRequest,
    service: SportsDataService = Depends(get_sports_service),
):
    """Generate EPG for teams."""
    orchestrator = Orchestrator(service)
    configs = _load_team_configs(request.team_ids)

    if not configs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active teams found",
        )

    options = TeamEPGOptions(days_ahead=request.days_ahead)
    result = orchestrator.generate_for_teams(configs, options)

    return EPGGenerateResponse(
        programmes_count=len(result.programmes),
        teams_processed=result.teams_processed,
        events_processed=0,
        duration_seconds=(result.completed_at - result.started_at).total_seconds(),
    )


@router.get("/epg/xmltv")
def get_xmltv(
    team_ids: str | None = Query(None, description="Comma-separated team IDs"),
    days_ahead: int = Query(14, ge=1, le=30),
    service: SportsDataService = Depends(get_sports_service),
):
    """Get XMLTV output for team-based EPG."""
    parsed_ids = _parse_team_ids(team_ids)
    orchestrator = Orchestrator(service)
    configs = _load_team_configs(parsed_ids)

    if not configs:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active teams found",
        )

    options = TeamEPGOptions(days_ahead=days_ahead)
    result = orchestrator.generate_for_teams(configs, options)

    return Response(
        content=result.xmltv,
        media_type="application/xml",
        headers={"Content-Disposition": "inline; filename=teamarr.xml"},
    )


# =============================================================================
# Event-based EPG endpoints
# =============================================================================


def _parse_date(date_str: str | None) -> date:
    """Parse date string or return today."""
    if not date_str:
        return date.today()
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid date format. Use YYYY-MM-DD.",
        ) from None


@router.post("/epg/events/generate", response_model=EPGGenerateResponse)
def generate_event_epg(
    request: EventEPGRequest,
    service: SportsDataService = Depends(get_sports_service),
):
    """Generate event-based EPG. Each event gets its own channel."""
    orchestrator = Orchestrator(service)
    target = _parse_date(request.target_date)

    options = EventEPGOptions(
        pregame_minutes=request.pregame_minutes,
        default_duration_hours=request.duration_hours,
    )

    result = orchestrator.generate_for_events(
        request.leagues, target, request.channel_prefix, options
    )

    return EPGGenerateResponse(
        programmes_count=len(result.programmes),
        teams_processed=0,
        events_processed=result.events_processed,
        duration_seconds=(result.completed_at - result.started_at).total_seconds(),
    )


@router.get("/epg/events/xmltv")
def get_event_xmltv(
    leagues: str = Query(..., description="Comma-separated league codes"),
    target_date: str | None = Query(None, description="Date (YYYY-MM-DD)"),
    channel_prefix: str = Query("event"),
    pregame_minutes: int = Query(30, ge=0, le=120),
    duration_hours: float = Query(3.0, ge=1.0, le=8.0),
    service: SportsDataService = Depends(get_sports_service),
):
    """Get XMLTV for event-based EPG. Each event gets its own channel."""
    league_list = [x.strip() for x in leagues.split(",") if x.strip()]
    if not league_list:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one league required",
        )

    orchestrator = Orchestrator(service)
    target = _parse_date(target_date)

    options = EventEPGOptions(
        pregame_minutes=pregame_minutes,
        default_duration_hours=duration_hours,
    )

    result = orchestrator.generate_for_events(league_list, target, channel_prefix, options)

    return Response(
        content=result.xmltv,
        media_type="application/xml",
        headers={"Content-Disposition": "inline; filename=teamarr-events.xml"},
    )


@router.post("/epg/events/match", response_model=EventMatchResponse)
def match_event(
    request: EventMatchRequest,
    service: SportsDataService = Depends(get_sports_service),
):
    """Match a query to a sporting event."""
    target = _parse_date(request.target_date)
    events = service.get_events(request.league, target)

    if not events:
        return EventMatchResponse(found=False)

    matcher = EventMatcher()

    if request.team1_id and request.team2_id:
        event = matcher.find_by_team_ids(events, request.team1_id, request.team2_id)
    elif request.team1_name and request.team2_name:
        event = matcher.find_by_team_names(events, request.team1_name, request.team2_name)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide either (team1_id, team2_id) or (team1_name, team2_name)",
        )

    if not event:
        return EventMatchResponse(found=False)

    return EventMatchResponse(
        found=True,
        event_id=event.id,
        event_name=event.name,
        home_team=event.home_team.name,
        away_team=event.away_team.name,
        start_time=event.start_time.isoformat(),
        venue=event.venue.name if event.venue else None,
    )
