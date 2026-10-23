"""Validated user-owned team fixtures for temporary event channels (#1131).

The first slice deliberately accepts configured team-vs-team leagues and teams
already in the identity cache. Custom teams/competitions and named sessions are
separate extensions, not fake teams forced through this contract.
"""

import sqlite3
from dataclasses import replace
from datetime import UTC
from typing import Literal
from uuid import uuid4

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from teamarr.core import Event, EventStatus, Team, Venue
from teamarr.database.leagues import get_league
from teamarr.database.manual_events import MANUAL_EVENT_PREFIX, get_manual_event, save_manual_event
from teamarr.database.team_cache import get_team_identity


class TeamReference(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    provider: str = Field(min_length=1, max_length=64)
    id: str = Field(min_length=1, max_length=128)


class ManualFixtureInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    league: str = Field(min_length=1, max_length=128)
    home_team: TeamReference
    away_team: TeamReference
    start_time: AwareDatetime
    name: str | None = Field(default=None, min_length=1, max_length=256)
    venue: str | None = Field(default=None, min_length=1, max_length=256)
    season_type: Literal["preseason", "regular", "postseason"] = "preseason"
    neutral_site: bool = False

    @model_validator(mode="after")
    def different_teams(self) -> "ManualFixtureInput":
        if self.home_team == self.away_team:
            raise ValueError("Home and away teams must be different")
        return self

    @field_validator("league")
    @classmethod
    def normalize_league(cls, value: str) -> str:
        """League codes are lowercase slugs everywhere else in Teamarr
        (leagues.league_code, team_cache.league, event matching). Storing any
        other case would silently hide the fixture from every candidate query,
        which are case-sensitive (#1131 review)."""
        return value.strip().lower()


def default_fixture_name(away_name: str, home_name: str, sport: str, neutral_site: bool) -> str:
    """ "At" for a hosted game, "vs" for soccer and neutral-site fixtures."""
    if neutral_site or sport == "soccer":
        return f"{away_name} vs {home_name}"
    return f"{away_name} at {home_name}"


def write_manual_fixture(
    conn: sqlite3.Connection, data: ManualFixtureInput, event_id: str | None = None
) -> Event:
    """Create/replace a fixture, never silently turn a typo into an upsert."""
    if event_id is not None:
        existing = get_manual_event(conn, event_id, data.league)
        if existing is None:
            raise LookupError("Manual fixture not found in this league")
        # Cancellation is permanent: retaining the row is what keeps a stale
        # reference from replaying, so PUT must not resurrect it (#1131 review).
        if existing.status.state == "cancelled":
            raise ValueError("Cannot edit a cancelled fixture")

    league = get_league(conn, data.league)
    if not league or league["event_type"] != "team_vs_team":
        raise ValueError("Choose an enabled, configured team-vs-team league")

    def resolve(ref: TeamReference, side: str) -> Team:
        identity = get_team_identity(conn, ref.provider, ref.id, data.league)
        if not identity:
            raise ValueError(
                f"{side} team {ref.provider}:{ref.id} does not exist in "
                f"the {data.league} team cache"
            )
        return Team(
            id=ref.id,
            provider=ref.provider,
            name=identity["name"],
            short_name=identity["short_name"] or identity["name"],
            abbreviation=identity["abbreviation"] or "",
            league=data.league,
            sport=league["sport"],
            logo_url=identity["logo_url"],
        )

    home, away = resolve(data.home_team, "Home"), resolve(data.away_team, "Away")
    event = Event(
        id=event_id or f"{MANUAL_EVENT_PREFIX}{uuid4()}",
        provider="manual",
        name=data.name
        or default_fixture_name(away.name, home.name, league["sport"], data.neutral_site),
        short_name=(
            f"{away.abbreviation or away.short_name} @ {home.abbreviation or home.short_name}"
            if not (data.neutral_site or league["sport"] == "soccer")
            else f"{away.abbreviation or away.short_name} vs {home.abbreviation or home.short_name}"
        ),
        start_time=data.start_time.astimezone(UTC),
        home_team=home,
        away_team=away,
        status=EventStatus(state="scheduled"),
        league=data.league,
        sport=league["sport"],
        venue=Venue(name=data.venue) if data.venue else None,
        season_type=data.season_type,
        neutral_site=data.neutral_site,
    )
    save_manual_event(conn, event)
    return event


def cancel_manual_fixture(
    conn: sqlite3.Connection, event_id: str, league: str | None = None
) -> Event:
    event = get_manual_event(conn, event_id, league)
    if event is None:
        raise LookupError("Manual fixture not found")
    event = replace(event, status=EventStatus(state="cancelled"))
    # No failure-cache purge: cancelling cannot make unmatched streams match.
    save_manual_event(conn, event, clear_cached_failures=False)
    return event
