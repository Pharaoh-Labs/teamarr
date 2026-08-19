"""Sports subscription API endpoints.

Global sports/league subscription and template assignment management.
"""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from teamarr.database import get_db
from teamarr.database.subscription import (
    add_subscription_template,
    delete_league_config,
    delete_subscription_template,
    get_league_configs,
    get_subscription_template,
    get_subscription_templates,
    update_subscription_template,
    upsert_league_config,
)
from teamarr.database.subscription import (
    get_subscription as db_get_subscription,
)
from teamarr.database.subscription import (
    update_subscription as db_update_subscription,
)

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
    sports: list[str] | None = Field(...)
    leagues: list[str] | None = Field(...)


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

    with get_db() as conn:
        assignment_id = add_subscription_template(
            conn,
            template_id=request.template_id,
            sports=request.sports,
            leagues=request.leagues,
        )
        template = get_subscription_template(conn, assignment_id)

    if template is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Template assignment could not be retrieved after creation",
        )

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

    if template is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Template assignment could not be retrieved after update",
        )

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

    with get_db() as conn:
        deleted = delete_league_config(conn, league_code)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No config found for league '{league_code}'",
        )
