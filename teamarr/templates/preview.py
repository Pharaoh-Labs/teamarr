"""Shared preview machinery: live TemplateContext building + static fallback.

Backs both GET /variables/samples (flattened variable map for the picker) and
POST /templates/preview (real-resolver render with condition trace, #357) so
the two surfaces can never drift: one context builder, one cache, one
fallback policy.
"""

import logging
import time

from teamarr.database import get_db
from teamarr.database.leagues import get_league
from teamarr.services.sports_data import create_default_service
from teamarr.templates.context import TemplateContext
from teamarr.templates.context_builder import ContextBuilder, find_adjacent_games
from teamarr.templates.sample_data import (
    AVAILABLE_SPORTS,
    get_all_sample_data,
    get_all_sample_data_for_league,
)

logger = logging.getLogger(__name__)

# Cache of live contexts keyed by league, with a short TTL so the preview
# stays responsive without hammering providers on every keystroke. Failures
# are NOT cached so a flaky provider recovers on the next request.
_LIVE_CTX_CACHE: dict[str, tuple[float, TemplateContext]] = {}
_LIVE_CTX_TTL = 300  # seconds


def lookup_league_fields(league_code: str) -> tuple[str | None, str | None]:
    """Get (sport, provider) for a league from its record, or (None, None)."""
    try:
        with get_db() as conn:
            rec = get_league(conn, league_code)
        if rec:
            return rec.get("sport"), rec.get("provider")
    except Exception as e:
        logger.debug("[SAMPLES] League lookup failed for %s: %s", league_code, e)
    return None, None


def build_live_context(league: str) -> TemplateContext | None:
    """Build a real TemplateContext from the best live event for a league.

    Returns None if no usable event could be found or the provider failed.
    Successful contexts are cached per league.
    """
    now = time.time()
    cached = _LIVE_CTX_CACHE.get(league)
    if cached and now - cached[0] < _LIVE_CTX_TTL:
        return cached[1]

    try:
        service = create_default_service()

        # Pick the best real event for the sample — prefers a just-completed game
        # so postgame vars (recap/scores/outcome) populate. Provider-aware fetch
        # keeps this to a couple of calls (TSDB uses a 2-call bulk path), so the
        # preview can't hammer rate-limited providers. None → static fallback.
        event = service.get_sample_event(league)
        if not event:
            return None

        # The sample event comes from the scoreboard, which carries free fields
        # (game_recap, etc.) but not the summary-only ones (game_preview,
        # series_summary). Refresh through the summary endpoint so the preview
        # shows exactly what generation produces. One cached call; the same
        # refresh generation already makes.
        event = service.refresh_event_status(event) or event

        team_id = event.home_team.id

        # Keep the chosen event (the best sample — ideally a just-completed game)
        # as the base; use the team's schedule only to fill .next/.last with real
        # adjacent games. (Previously this overwrote the base with the next
        # scheduled game, blanking postgame vars like recap/score/winner.)
        next_event = last_event = None
        schedule = service.get_team_schedule(team_id, league)
        if schedule:
            next_event, last_event = find_adjacent_games(schedule, event)

        ctx = ContextBuilder(service).build_for_event(
            event=event,
            team_id=team_id,
            league=league,
            next_event=next_event,
            last_event=last_event,
        )
        _LIVE_CTX_CACHE[league] = (now, ctx)
        return ctx
    except Exception as e:  # provider down, unsupported league, etc.
        logger.info("[SAMPLES] Live context build failed for %s: %s", league, e)
        return None


def build_static_samples(league: str | None, sport: str = "NBA") -> dict[str, str]:
    """Static sample variable map for a league (or a sport profile fallback)."""
    if league:
        league_sport, league_provider = lookup_league_fields(league)
        return get_all_sample_data_for_league(league, league_sport, league_provider)
    if sport not in AVAILABLE_SPORTS:
        sport = "NBA"
    return get_all_sample_data(sport)
