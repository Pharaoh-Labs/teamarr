"""Sports subscription API endpoints.

Global sports/league subscription and template assignment management.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from teamarr.database import get_db

router = APIRouter()


# =============================================================================
# PYDANTIC MODELS
# =============================================================================


class SubscriptionResponse(BaseModel):
    """Sports subscription response."""

    id: int = 1
    leagues: list[str] = []
    soccer_mode: str | None = None
    soccer_followed_teams: list[dict] | None = None
    updated_at: str | None = None


class SubscriptionUpdate(BaseModel):
    """Update sports subscription request."""

    leagues: list[str] | None = None
    soccer_mode: str | None = None
    soccer_followed_teams: list[dict] | None = None


class TemplateAssignmentResponse(BaseModel):
    """Subscription template assignment response."""

    id: int
    template_id: int
    sports: list[str] | None = None
    leagues: list[str] | None = None
    template_name: str | None = None


class TemplateAssignmentCreate(BaseModel):
    """Create subscription template assignment."""

    template_id: int
    sports: list[str] | None = None
    leagues: list[str] | None = None


class TemplateAssignmentUpdate(BaseModel):
    """Update subscription template assignment."""

    template_id: int | None = None
    sports: list[str] | None = ...
    leagues: list[str] | None = ...


class TemplateAssignmentListResponse(BaseModel):
    """List of subscription template assignments."""

    templates: list[TemplateAssignmentResponse]
    total: int


class LeagueConfigResponse(BaseModel):
    """Per-league subscription config response."""

    league_code: str
    channel_profile_ids: list[int | str] | None = None
    channel_group_id: int | None = None
    channel_group_mode: str | None = None


class LeagueConfigUpdate(BaseModel):
    """Update per-league subscription config."""

    channel_profile_ids: list[int | str] | None = None
    channel_group_id: int | None = None
    channel_group_mode: str | None = None


class LeagueConfigListResponse(BaseModel):
    """List of per-league subscription configs."""

    configs: list[LeagueConfigResponse]
    total: int


# =============================================================================
# SUBSCRIPTION ENDPOINTS
# =============================================================================


@router.get(
    "/sports-subscription",
    response_model=SubscriptionResponse,
)
def get_subscription():
    """Get the global sports subscription."""
    from teamarr.database.subscription import (
        get_subscription as db_get_subscription,
    )

    with get_db() as conn:
        sub = db_get_subscription(conn)

    return SubscriptionResponse(
        id=sub.id,
        leagues=sub.leagues,
        soccer_mode=sub.soccer_mode,
        soccer_followed_teams=sub.soccer_followed_teams,
        updated_at=sub.updated_at,
    )


@router.put(
    "/sports-subscription",
    response_model=SubscriptionResponse,
)
def update_subscription(request: SubscriptionUpdate):
    """Update the global sports subscription."""
    from teamarr.database.subscription import (
        update_subscription as db_update_subscription,
    )

    kwargs = {}
    if request.leagues is not None:
        kwargs["leagues"] = request.leagues
    if request.soccer_mode is not ...:
        kwargs["soccer_mode"] = request.soccer_mode
    if request.soccer_followed_teams is not ...:
        kwargs["soccer_followed_teams"] = request.soccer_followed_teams

    with get_db() as conn:
        sub = db_update_subscription(conn, **kwargs)

    return SubscriptionResponse(
        id=sub.id,
        leagues=sub.leagues,
        soccer_mode=sub.soccer_mode,
        soccer_followed_teams=sub.soccer_followed_teams,
        updated_at=sub.updated_at,
    )


# =============================================================================
# SUBSCRIPTION TEMPLATE ENDPOINTS
# =============================================================================


@router.get(
    "/subscription-templates",
    response_model=TemplateAssignmentListResponse,
)
def list_subscription_templates():
    """List all global template assignments."""
    from teamarr.database.subscription import get_subscription_templates

    with get_db() as conn:
        templates = get_subscription_templates(conn)

    return TemplateAssignmentListResponse(
        templates=[
            TemplateAssignmentResponse(
                id=t.id,
                template_id=t.template_id,
                sports=t.sports,
                leagues=t.leagues,
                template_name=t.template_name,
            )
            for t in templates
        ],
        total=len(templates),
    )


@router.post(
    "/subscription-templates",
    response_model=TemplateAssignmentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_subscription_template(request: TemplateAssignmentCreate):
    """Add a global template assignment."""
    from teamarr.database.subscription import (
        add_subscription_template,
        get_subscription_template,
    )

    with get_db() as conn:
        assignment_id = add_subscription_template(
            conn,
            template_id=request.template_id,
            sports=request.sports,
            leagues=request.leagues,
        )
        template = get_subscription_template(conn, assignment_id)

    return TemplateAssignmentResponse(
        id=template.id,
        template_id=template.template_id,
        sports=template.sports,
        leagues=template.leagues,
        template_name=template.template_name,
    )


@router.put(
    "/subscription-templates/{assignment_id}",
    response_model=TemplateAssignmentResponse,
)
def update_subscription_template_endpoint(
    assignment_id: int, request: TemplateAssignmentUpdate
):
    """Update a global template assignment."""
    from teamarr.database.subscription import (
        get_subscription_template,
        update_subscription_template,
    )

    with get_db() as conn:
        existing = get_subscription_template(conn, assignment_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template assignment {assignment_id} not found",
            )

        kwargs = {}
        if request.template_id is not None:
            kwargs["template_id"] = request.template_id
        if request.sports is not ...:
            kwargs["sports"] = request.sports
        if request.leagues is not ...:
            kwargs["leagues"] = request.leagues

        update_subscription_template(conn, assignment_id, **kwargs)
        template = get_subscription_template(conn, assignment_id)

    return TemplateAssignmentResponse(
        id=template.id,
        template_id=template.template_id,
        sports=template.sports,
        leagues=template.leagues,
        template_name=template.template_name,
    )


@router.delete(
    "/subscription-templates/{assignment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_subscription_template_endpoint(assignment_id: int):
    """Delete a global template assignment."""
    from teamarr.database.subscription import (
        delete_subscription_template,
        get_subscription_template,
    )

    with get_db() as conn:
        existing = get_subscription_template(conn, assignment_id)
        if not existing:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template assignment {assignment_id} not found",
            )

        delete_subscription_template(conn, assignment_id)


# =============================================================================
# SUBSCRIPTION LEAGUE CONFIG ENDPOINTS
# =============================================================================


@router.get(
    "/league-configs",
    response_model=LeagueConfigListResponse,
)
def list_league_configs():
    """List all per-league subscription configs."""
    from teamarr.database.subscription import get_league_configs

    with get_db() as conn:
        configs = get_league_configs(conn)

    return LeagueConfigListResponse(
        configs=[
            LeagueConfigResponse(
                league_code=c.league_code,
                channel_profile_ids=c.channel_profile_ids,
                channel_group_id=c.channel_group_id,
                channel_group_mode=c.channel_group_mode,
            )
            for c in configs
        ],
        total=len(configs),
    )


@router.put(
    "/league-configs/{league_code}",
    response_model=LeagueConfigResponse,
)
def upsert_league_config_endpoint(league_code: str, request: LeagueConfigUpdate):
    """Create or update per-league subscription config."""
    from teamarr.database.subscription import upsert_league_config

    with get_db() as conn:
        config = upsert_league_config(
            conn,
            league_code=league_code,
            channel_profile_ids=request.channel_profile_ids,
            channel_group_id=request.channel_group_id,
            channel_group_mode=request.channel_group_mode,
        )

    return LeagueConfigResponse(
        league_code=config.league_code,
        channel_profile_ids=config.channel_profile_ids,
        channel_group_id=config.channel_group_id,
        channel_group_mode=config.channel_group_mode,
    )


@router.delete(
    "/league-configs/{league_code}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_league_config_endpoint(league_code: str):
    """Delete per-league subscription config."""
    from teamarr.database.subscription import delete_league_config

    with get_db() as conn:
        deleted = delete_league_config(conn, league_code)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No config found for league '{league_code}'",
        )


# =============================================================================
# TEAM EPG COMPETITION FILTER
# =============================================================================


class CompetitionFilterUpdate(BaseModel):
    """Set the EPG competition filter for a league.

    competition_filter: list of league codes to allow in team channel EPG,
    or null/empty to include all competitions (clear the filter).
    """

    competition_filter: list[str] | None = None


class CompetitionFilterResponse(BaseModel):
    league_code: str
    competition_filter: list[str] | None


@router.get(
    "/leagues/{league_code}/competition-filter",
    response_model=CompetitionFilterResponse,
)
def get_competition_filter(league_code: str):
    """Get the EPG competition filter for a league's team channels."""
    from teamarr.database.leagues import get_league_competition_filter

    with get_db() as conn:
        f = get_league_competition_filter(conn, league_code)

    return CompetitionFilterResponse(league_code=league_code, competition_filter=f)


@router.put(
    "/leagues/{league_code}/competition-filter",
    response_model=CompetitionFilterResponse,
)
def set_competition_filter(league_code: str, request: CompetitionFilterUpdate):
    """Set (or clear) the EPG competition filter for a league's team channels.

    Pass competition_filter as a list of league codes to restrict team EPG to
    only those competitions. Pass null or an empty list to remove the filter
    and restore default behaviour (all competitions included).

    Example — restrict EPL team channels to EPL fixtures only:
        PUT /api/v1/leagues/eng.1/competition-filter
        {"competition_filter": ["eng.1"]}
    """
    from teamarr.database.leagues import set_league_competition_filter

    # Treat empty list the same as null (clear the filter)
    codes = request.competition_filter if request.competition_filter else None

    with get_db() as conn:
        set_league_competition_filter(conn, league_code, codes)

    return CompetitionFilterResponse(league_code=league_code, competition_filter=codes)
