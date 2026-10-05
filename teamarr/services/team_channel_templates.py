"""Team channel name and logo templates, resolved in one place (#983).

A team template's ``team_channel_name`` and ``team_channel_logo_url`` are
rendered for the guide (team processor), for Dispatcharr (team channel
manager) and for the Channels page. Each used to carry its own copy of a
four-entry variable map, so any other variable — ``{league_abbrev}``,
``{team_short}`` — stayed literal in the channel name. They now share this
module, which runs the real template engine against the team alone.

There is no game here: a channel's name must not change from run to run, so
game- and stats-backed variables resolve empty, exactly as they do in any
other gameless context.
"""

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from sqlite3 import Connection
from typing import TYPE_CHECKING, Any

from teamarr.database.leagues import get_league_display
from teamarr.database.team_cache import get_team_identity
from teamarr.utilities.art_url import apply_art_base_url, is_relative_art_path

if TYPE_CHECKING:
    from teamarr.templates.context import TemplateContext

# teamarr.templates is imported inside the functions: this module is reached
# from teamarr.services, which the template package itself imports.


def _fields(team: Any) -> Mapping:
    """A teams-table row as a mapping, whichever shape the caller holds."""
    if isinstance(team, Mapping):
        return team
    if is_dataclass(team) and not isinstance(team, type):
        return asdict(team)
    raise TypeError(f"team must be a mapping or a dataclass, not {type(team).__name__}")


def team_channel_context(conn: Connection, team: Any) -> "TemplateContext":
    """Gameless template context for one team's channel."""
    from teamarr.templates.context import TeamChannelContext, TemplateContext

    row = _fields(team)
    league = row["primary_league"]
    provider_team_id = row.get("provider_team_id")
    cached = None
    if row.get("provider") and provider_team_id:
        cached = get_team_identity(conn, row["provider"], str(provider_team_id), league)
    cached = cached or {}

    config = TeamChannelContext(
        team_id=str(provider_team_id or ""),
        league=league,
        sport=row.get("sport") or "",
        team_name=row["team_name"],
        team_abbrev=row.get("team_abbrev") or cached.get("abbreviation"),
        team_short_name=cached.get("short_name"),
        team_logo_url=row.get("team_logo_url"),
        channel_id=row.get("channel_id"),
    )
    return TemplateContext(
        game_context=None,
        team_config=config,
        team_stats=None,
        # The four variables these fields have always resolved keep the values
        # they have always had, so no existing channel is renamed and no logo
        # URL moves: {league_id} here is the league code, where the engine's
        # own extractor would answer with the league's art id.
        extra_vars={
            "league": get_league_display(conn, league),
            "league_id": league,
            "league_code": league,
            "team_name": row["team_name"],
        },
    )


def resolve_team_channel_name(conn: Connection, team: Any, name_template: str | None) -> str:
    """The team channel's name; the team name when the template sets none."""
    from teamarr.templates.resolver import TemplateResolver

    row = _fields(team)
    if not name_template:
        return row["team_name"]
    return TemplateResolver().resolve(name_template, team_channel_context(conn, row))


def resolve_team_channel_logo(
    conn: Connection, team: Any, logo_template: str | None, art_base_url: str
) -> str | None:
    """The team channel's template logo URL, or None when there is none to use.

    None covers both "the template sets no logo" and "the template resolves to
    a game-thumbs path with no base URL configured" — not a URL anything can
    fetch (#826). Callers decide what stands in for it.
    """
    from teamarr.templates.resolver import TemplateResolver

    if not logo_template:
        return None
    resolved = TemplateResolver(art_base_url).resolve(
        logo_template, team_channel_context(conn, team)
    )
    resolved = apply_art_base_url(resolved, art_base_url)
    return None if is_relative_art_path(resolved) else resolved
