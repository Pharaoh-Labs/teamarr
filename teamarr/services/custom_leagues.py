"""Custom-league policy: premium gate and sport guardrails.

Single source of truth for the rules that govern user-added (custom) leagues
(epic ``teamarrv2-eqz``). Custom leagues are TSDB-only and the whole feature is
gated behind a TheSportsDB *premium* key. These helpers are consumed by the
custom-league write routes (``eqz.2``) and the live test-fetch / validation
endpoint (``eqz.3``); keeping them here means the UI, the write path, and the
validator all enforce the same policy.

Why a hard premium gate (``eqz.1``):
    TSDB's free tier is too thin for arbitrary leagues — ``eventsnextleague``
    returns ~5 events/day and ``lookupteam`` is broken — so a free-tier custom
    league would silently produce empty guides. Gating on a premium key keeps
    that failure mode out of the product.

Why sport guardrails (``eqz.8``):
    A league's ``sport`` selects which matcher and ``event_type`` logic runs. A
    free-text or unsupported sport routes the league through the wrong pipeline
    and silently emits broken channels. We therefore restrict custom leagues to
    the sports that actually have a working matcher, and cross-check the chosen
    sport against what TSDB reports for the league.
"""

from __future__ import annotations

import logging
import sqlite3

from teamarr.consumers.cache.refresh import CacheRefresher
from teamarr.database import get_db
from teamarr.database.groups import get_enabled_soccer_leagues
from teamarr.database.leagues import (
    delete_custom_league_row,
    get_league_row,
    insert_custom_league,
    list_custom_leagues,
    purge_league_cache_rows,
    update_custom_league_row,
)
from teamarr.database.settings.read import get_tsdb_api_key
from teamarr.database.subscription import get_subscription, update_subscription
from teamarr.providers.tsdb import TSDBClient
from teamarr.services.league_mappings import get_league_mapping_service

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sport guardrails (eqz.8)
# ---------------------------------------------------------------------------

# Sports that have a working matcher today. This is intentionally NARROWER than
# the ``sports`` table (17 rows): tennis, golf, racing, and wrestling are seeded
# as placeholders for roadmap epics (mf7 tennis, 1tz golf, h31 motorsports) but
# have no matcher, so a custom league under them would generate broken output.
# When one of those sports ships a real matcher, add its code here.
FUNCTIONAL_SPORTS: frozenset[str] = frozenset(
    {
        "australian-football",
        "baseball",
        "basketball",
        "boxing",
        "cricket",
        "football",
        "hockey",
        "lacrosse",
        "mma",
        "rugby",
        "soccer",
        "softball",
        "volleyball",
    }
)

# The only ``event_type`` values the matching pipeline understands.
ALLOWED_EVENT_TYPES: frozenset[str] = frozenset({"team_vs_team", "event_card"})

# Sports whose events are cards of individual bouts rather than two-team games;
# these default to ``event_card``. Everything else defaults to ``team_vs_team``.
_EVENT_CARD_SPORTS: frozenset[str] = frozenset({"boxing", "mma"})

# Maps TSDB ``strSport`` values to Teamarr sport codes. Used to cross-check the
# user's chosen sport against what TSDB actually reports for the league. Any
# value not present here resolves to ``None`` and fails the cross-check, which
# is the safe default (reject rather than mislabel).
_TSDB_SPORT_TO_TEAMARR: dict[str, str] = {
    "soccer": "soccer",
    "cricket": "cricket",
    "rugby": "rugby",
    "boxing": "boxing",
    "fighting": "mma",
    "ice hockey": "hockey",
    "baseball": "baseball",
    "basketball": "basketball",
    "american football": "football",
    "australian football": "australian-football",
    "volleyball": "volleyball",
    "lacrosse": "lacrosse",
    "softball": "softball",
}


class CustomLeagueValidationError(ValueError):
    """A custom-league field failed a guardrail (maps to HTTP 400)."""


class CustomLeagueGateError(PermissionError):
    """The custom-league feature is locked (no premium key; maps to HTTP 403)."""


class CustomLeagueNotFoundError(LookupError):
    """No league exists for the given code (maps to HTTP 404)."""


class CustomLeagueProtectedError(PermissionError):
    """The target league is a built-in and can't be edited/deleted (HTTP 403)."""


# ---------------------------------------------------------------------------
# Premium gate (eqz.1)
# ---------------------------------------------------------------------------


def custom_leagues_enabled(conn: sqlite3.Connection) -> bool:
    """Return whether the custom-league feature is unlocked for this install.

    The single gate signal is the presence of a TheSportsDB premium key in
    settings — the same key that flips the TSDB client into premium mode
    (``providers/__init__.py``).
    """
    key = get_tsdb_api_key(conn)
    return bool(key and key.strip())


def require_custom_leagues_enabled(conn: sqlite3.Connection) -> None:
    """Raise :class:`CustomLeagueGateError` if the feature is locked."""
    if not custom_leagues_enabled(conn):
        raise CustomLeagueGateError(
            "Custom leagues require a TheSportsDB premium key. "
            "Add one in Settings > System > TheSportsDB API Key."
        )


# ---------------------------------------------------------------------------
# Sport / event-type helpers
# ---------------------------------------------------------------------------


def is_supported_sport(sport: str) -> bool:
    """Return whether ``sport`` is a matcher-backed (functional) sport."""
    return sport in FUNCTIONAL_SPORTS


def supported_custom_league_sports(conn: sqlite3.Connection) -> list[dict]:
    """List functional sports as ``{sport_code, display_name}`` for the UI.

    Intersects the ``sports`` table (for display names) with
    :data:`FUNCTIONAL_SPORTS`, sorted by display name. This is what the
    custom-league form's sport dropdown should offer — never free text.
    """
    rows = conn.execute(
        "SELECT sport_code, display_name FROM sports ORDER BY display_name"
    ).fetchall()
    return [
        {"sport_code": r["sport_code"], "display_name": r["display_name"]}
        for r in rows
        if r["sport_code"] in FUNCTIONAL_SPORTS
    ]


def default_event_type(sport: str) -> str:
    """Return the sensible default ``event_type`` for a sport."""
    return "event_card" if sport in _EVENT_CARD_SPORTS else "team_vs_team"


def tsdb_sport_to_teamarr(tsdb_str_sport: str | None) -> str | None:
    """Map a TSDB ``strSport`` to a Teamarr sport code (None if unmapped)."""
    if not tsdb_str_sport:
        return None
    return _TSDB_SPORT_TO_TEAMARR.get(tsdb_str_sport.strip().lower())


def validate_custom_league_sport(sport: str) -> None:
    """Raise :class:`CustomLeagueValidationError` if ``sport`` isn't functional."""
    if sport not in FUNCTIONAL_SPORTS:
        raise CustomLeagueValidationError(
            f"Sport '{sport}' is not supported for custom leagues. "
            f"Choose one of: {', '.join(sorted(FUNCTIONAL_SPORTS))}."
        )


def validate_event_type(event_type: str) -> None:
    """Raise :class:`CustomLeagueValidationError` for an unknown ``event_type``."""
    if event_type not in ALLOWED_EVENT_TYPES:
        raise CustomLeagueValidationError(
            f"event_type '{event_type}' is invalid. "
            f"Must be one of: {', '.join(sorted(ALLOWED_EVENT_TYPES))}."
        )


def validate_tsdb_sport_matches(tsdb_str_sport: str | None, chosen_sport: str) -> None:
    """Cross-check TSDB's sport for a league against the user's chosen sport.

    Prevents mislabeling (e.g. picking ``soccer`` for a league TSDB classifies
    as cricket), which would route the league through the wrong matcher. An
    unmapped TSDB sport is treated as a mismatch — reject rather than guess.
    """
    mapped = tsdb_sport_to_teamarr(tsdb_str_sport)
    if mapped is None:
        raise CustomLeagueValidationError(
            f"TheSportsDB reports sport '{tsdb_str_sport}', which Teamarr does "
            "not support for custom leagues."
        )
    if mapped != chosen_sport:
        raise CustomLeagueValidationError(
            f"Sport mismatch: you selected '{chosen_sport}' but TheSportsDB "
            f"classifies this league as '{mapped}' (strSport '{tsdb_str_sport}')."
        )


# ---------------------------------------------------------------------------
# Write path (eqz.2)
#
# These wrap the raw row I/O in database/leagues.py with the full policy stack:
# premium gate, TSDB-only, field/sport/event_type validation, code-collision
# guard, and built-in protection (edits/deletes only ever touch is_custom=1
# rows). Routes call these and translate the exception types to HTTP codes.
# ---------------------------------------------------------------------------

_ALLOWED_TSDB_TIERS: frozenset[str] = frozenset({"free", "premium"})


def _require_tsdb(provider: str) -> None:
    """Reject any non-TSDB provider (the epic's #1 non-negotiable constraint)."""
    if provider != "tsdb":
        raise CustomLeagueValidationError(
            f"Custom leagues are TheSportsDB-only; provider '{provider}' is not "
            "allowed. Only 'tsdb' is supported."
        )


def _clean_required(value: str | None, field: str) -> str:
    """Return a stripped non-empty string or raise a validation error."""
    cleaned = (value or "").strip()
    if not cleaned:
        raise CustomLeagueValidationError(f"{field} is required.")
    return cleaned


def _validate_tier(tsdb_tier: str | None) -> str | None:
    """Normalize/validate the optional tsdb_tier ('free' | 'premium' | None)."""
    if tsdb_tier is None or not tsdb_tier.strip():
        return None
    tier = tsdb_tier.strip().lower()
    if tier not in _ALLOWED_TSDB_TIERS:
        raise CustomLeagueValidationError(
            f"tsdb_tier '{tsdb_tier}' is invalid. Must be 'free' or 'premium'."
        )
    return tier


def _resolve_event_type(event_type: str | None, sport: str) -> str:
    """Default the event_type from the sport when omitted, then validate it."""
    resolved = (event_type or "").strip() or default_event_type(sport)
    validate_event_type(resolved)
    return resolved


def create_custom_league(
    conn: sqlite3.Connection,
    *,
    league_code: str,
    provider: str = "tsdb",
    provider_league_id: str,
    provider_league_name: str,
    display_name: str,
    sport: str,
    event_type: str | None = None,
    tsdb_tier: str | None = None,
    allow_empty: bool = False,
) -> dict:
    """Create a user-added custom league after enforcing all policy.

    Before writing the row, this re-runs the live TSDB validation server-side
    (eqz.3) — the UI's pre-save check is advisory, this is the authoritative
    guardrail. It confirms the id resolves and the sport matches, and blocks the
    save when TSDB returns zero upcoming events (the silent-empty-guide failure
    mode). ``allow_empty=True`` is the deliberate override for a genuinely
    off-season league.

    Raises:
        CustomLeagueGateError: feature locked (no premium key) → 403.
        CustomLeagueValidationError: bad provider/field/sport/collision, an
            unresolvable id, a sport mismatch, or zero events without override.
    """
    require_custom_leagues_enabled(conn)
    _require_tsdb(provider)

    code = _clean_required(league_code, "league_code").lower()
    provider_id = _clean_required(provider_league_id, "provider_league_id")
    provider_name = _clean_required(provider_league_name, "provider_league_name")
    name = _clean_required(display_name, "display_name")
    validate_custom_league_sport(sport)
    resolved_event_type = _resolve_event_type(event_type, sport)
    tier = _validate_tier(tsdb_tier)

    # Collision guard: never let a custom row shadow an existing code (built-in
    # OR an already-created custom). INSERT OR REPLACE would clobber built-ins.
    if get_league_row(conn, code) is not None:
        raise CustomLeagueValidationError(
            f"League code '{code}' already exists. Choose a different code."
        )

    # Authoritative live guardrail (eqz.3): resolves the id, cross-checks the
    # sport, and refuses to persist a league that returns no events unless the
    # caller explicitly overrides for an off-season league.
    report = run_custom_league_test_fetch(
        conn,
        provider_league_id=provider_id,
        chosen_sport=sport,
        provider_league_name=provider_name,
    )
    if report["event_count"] == 0 and not allow_empty:
        raise CustomLeagueValidationError(
            f"TheSportsDB returned no upcoming events for league id '{provider_id}' "
            f"(resolved as '{report['tsdb_league_name']}'). This usually means a "
            "wrong idLeague or an off-season league. Re-submit with allow_empty=true "
            "to save anyway."
        )

    insert_custom_league(
        conn,
        league_code=code,
        provider_league_id=provider_id,
        provider_league_name=provider_name,
        display_name=name,
        sport=sport,
        event_type=resolved_event_type,
        tsdb_tier=tier,
    )
    _auto_subscribe(conn, code)
    row = get_league_row(conn, code)
    assert row is not None  # row just created above
    return row


def _auto_subscribe(conn: sqlite3.Connection, league_code: str) -> None:
    """Add a freshly-created custom league to the global sports subscription.

    Every event group resolves its match/inclusion leagues from the global
    ``sports_subscription`` (see ``_resolve_subscription_leagues``), so a custom
    league the user never explicitly subscribes to produces zero matches
    (``no_event_found``) and zero included events — the exact GH #240 footgun.
    Subscribing on create closes that gap so a newly-added league "just works".

    Idempotent: a code already in the list is left untouched. Note a soccer
    league in ``soccer_mode='all'`` is matched via the all-soccer expansion
    regardless, so this is a no-op-but-harmless add in that mode.
    """

    sub = get_subscription(conn)
    if league_code in sub.leagues:
        return
    update_subscription(conn, leagues=[*sub.leagues, league_code])
    logger.info(
        "[CUSTOM_LEAGUE] Auto-subscribed %s to the global sports subscription",
        league_code,
    )


def global_subscription_league_codes(conn: sqlite3.Connection) -> set[str]:
    """Effective set of league codes the global subscription will match.

    Mirrors the global branch of ``_resolve_subscription_leagues`` (including the
    ``soccer_mode='all'`` expansion) so the UI's "subscribed?" signal matches what
    generation actually includes. Per-group subscription overrides are not
    considered here — this is the install-wide default a custom league lands in.
    """

    sub = get_subscription(conn)
    codes: set[str] = set(sub.leagues)
    if sub.soccer_mode == "all":
        codes.update(get_enabled_soccer_leagues(conn))
    return codes


def list_custom_leagues_with_state(conn: sqlite3.Connection) -> list[dict]:
    """List custom leagues, each annotated with a ``subscribed`` flag.

    ``subscribed=False`` is the #240 warning signal: the league exists but the
    global subscription won't match its events, so it silently produces nothing
    until the user subscribes it. Creation auto-subscribes (:func:`_auto_subscribe`),
    so this only trips when a user later unchecks the league in Subscriptions.
    """

    subscribed = global_subscription_league_codes(conn)
    return [
        {**row, "subscribed": row["league_code"] in subscribed}
        for row in list_custom_leagues(conn)
    ]


def _load_custom_or_raise(conn: sqlite3.Connection, league_code: str) -> dict:
    """Fetch a league row and assert it's an editable custom row.

    Raises:
        CustomLeagueNotFoundError: no such code → 404.
        CustomLeagueProtectedError: code exists but is a built-in → 403.
    """
    row = get_league_row(conn, league_code.lower())
    if row is None:
        raise CustomLeagueNotFoundError(f"No league with code '{league_code}'.")
    if not row.get("is_custom"):
        raise CustomLeagueProtectedError(
            f"League '{league_code}' is a built-in and cannot be modified or "
            "deleted via the custom-league API."
        )
    return row


def update_custom_league(
    conn: sqlite3.Connection,
    league_code: str,
    *,
    provider_league_id: str,
    provider_league_name: str,
    display_name: str,
    sport: str,
    event_type: str | None = None,
    tsdb_tier: str | None = None,
) -> dict:
    """Update an existing custom league (built-ins rejected with 403)."""
    require_custom_leagues_enabled(conn)
    code = league_code.lower()
    _load_custom_or_raise(conn, code)

    provider_id = _clean_required(provider_league_id, "provider_league_id")
    provider_name = _clean_required(provider_league_name, "provider_league_name")
    name = _clean_required(display_name, "display_name")
    validate_custom_league_sport(sport)
    resolved_event_type = _resolve_event_type(event_type, sport)
    tier = _validate_tier(tsdb_tier)

    update_custom_league_row(
        conn,
        code,
        provider_league_id=provider_id,
        provider_league_name=provider_name,
        display_name=name,
        sport=sport,
        event_type=resolved_event_type,
        tsdb_tier=tier,
    )
    row = get_league_row(conn, code)
    assert row is not None  # row just upserted above
    return row


def delete_custom_league(conn: sqlite3.Connection, league_code: str) -> None:
    """Delete an existing custom league (built-ins rejected with 403).

    Removes the ``leagues`` row and its cached ``team_cache``/``league_cache``
    rows in one transaction, mirroring the create path so no orphaned teams or
    league entry linger behind (eqz.9).
    """
    require_custom_leagues_enabled(conn)
    code = league_code.lower()
    _load_custom_or_raise(conn, code)
    delete_custom_league_row(conn, code)
    teams, leagues = purge_league_cache_rows(conn, code)
    logger.info(
        "[CUSTOM_LEAGUE] Deleted %s — purged %d team_cache + %d league_cache rows",
        code,
        teams,
        leagues,
    )


# ---------------------------------------------------------------------------
# Live test-fetch / validation (eqz.3)
#
# The epic's central risk: a custom-league form that just writes a row turns a
# wrong provider_league_name into a silent empty guide that *looks* like a
# Teamarr bug. This validator hits TSDB live BEFORE save: it confirms the id
# resolves, cross-checks the sport, and pulls upcoming events so the UI can show
# the user real fixtures (or an explicit "no events found") to confirm against.
# ---------------------------------------------------------------------------

# How many upcoming events to surface back to the UI as a sanity check.
_TEST_FETCH_SAMPLE_LIMIT = 5


def _sample_event(event: dict) -> dict:
    """Project a raw TSDB event down to the fields the UI shows for confirmation."""
    return {
        "name": event.get("strEvent"),
        "home": event.get("strHomeTeam"),
        "away": event.get("strAwayTeam"),
        "date": event.get("dateEvent"),
        "timestamp": event.get("strTimestamp"),
    }


def run_custom_league_test_fetch(
    conn: sqlite3.Connection,
    *,
    provider_league_id: str,
    chosen_sport: str,
    provider_league_name: str | None = None,
) -> dict:
    """Live-validate a prospective custom league against TheSportsDB.

    Builds a premium TSDB client (the feature is gated on a premium key), looks
    the league up by id, cross-checks its sport, and fetches upcoming events.
    Returns a UI-friendly report rather than raising on "no events" — an empty
    upcoming slate is a legitimate state the user should see (off-season), not an
    error; the create guardrail decides whether to block on it.

    When ``provider_league_name`` is supplied it is compared (case-insensitively)
    against TSDB's canonical ``strLeague`` and surfaced as ``name_matches`` — the
    signal that helps a user tell a wrong *id* from a wrong *name*, since the TSDB
    provider uses the id for some endpoints and the exact name for others.

    Raises:
        CustomLeagueGateError: feature locked (no premium key) → 403.
        CustomLeagueValidationError: id missing/unresolvable, or sport mismatch.
    """
    require_custom_leagues_enabled(conn)
    league_id = _clean_required(provider_league_id, "provider_league_id")
    validate_custom_league_sport(chosen_sport)

    # Imported lazily so the policy module stays import-light and test-friendly.

    client = TSDBClient(api_key=get_tsdb_api_key(conn))

    league = client.lookup_league_raw(league_id)
    if league is None:
        raise CustomLeagueValidationError(
            f"TheSportsDB has no league with id '{league_id}'. Check the idLeague."
        )

    tsdb_str_sport = league.get("strSport")
    # Surfaces the precise mismatch message; re-raised as a validation error.
    validate_tsdb_sport_matches(tsdb_str_sport, chosen_sport)

    tsdb_name = league.get("strLeague")
    name_matches: bool | None = None
    if provider_league_name and provider_league_name.strip():
        name_matches = provider_league_name.strip().casefold() == (tsdb_name or "").casefold()

    raw = client.get_next_events_raw(league_id)
    events = (raw or {}).get("events") or []
    samples = [_sample_event(e) for e in events[:_TEST_FETCH_SAMPLE_LIMIT]]

    return {
        "ok": True,
        # Which endpoint produced the result, so a user can debug id vs name:
        # the league identity comes from lookupleague(id) and the fixtures from
        # eventsnextleague(id). Both are id-keyed; name_matches flags a bad name.
        "resolved_via": "eventsnextleague",
        "provider_league_id": league_id,
        "tsdb_league_name": tsdb_name,
        "name_matches": name_matches,
        "tsdb_sport": tsdb_str_sport,
        "chosen_sport": chosen_sport,
        "event_count": len(events),
        "sample_events": samples,
    }


# ---------------------------------------------------------------------------
# Create + auto team-cache refresh (eqz.4)
#
# A freshly-created league has cached_team_count=0 until a refresh runs. Rather
# than wait for the weekly schedule or a full manual refresh, we kick a scoped
# refresh of just this league right after create commits, so its teams populate
# immediately. The refresh is best-effort: a provider/network hiccup leaves the
# league created with a "teams not yet cached" state instead of failing the save.
# Note teams populate even for an off-season league — team rosters exist
# year-round, unlike the upcoming-events feed the create guardrail checks.
# ---------------------------------------------------------------------------


def refresh_custom_league_teams(league_code: str) -> dict:
    """Best-effort scoped team-cache refresh for one league. Never raises.

    Returns the refresher's result dict, or a ``success=False`` dict if the
    refresh machinery itself blows up.
    """

    try:
        return CacheRefresher().refresh_league(league_code)
    except Exception as e:  # noqa: BLE001 — the league is already saved; don't surface
        logger.warning("[CUSTOM_LEAGUE] Team refresh for %s failed: %s", league_code, e)
        return {"success": False, "league_code": league_code, "team_count": 0, "error": str(e)}


def create_custom_league_and_refresh(**fields) -> dict:
    """Create a custom league, commit, then scope-refresh its teams.

    The create runs in its own transaction (so the row is committed and visible
    to the provider's league-mapping lookup) before the team refresh fires on a
    separate connection. Returns the created league row with a ``team_refresh``
    summary attached. The team refresh is best-effort and never fails the create.

    Between the two, the in-memory league-mapping cache is reloaded: providers
    resolve ``league_code`` → provider league name/id through that cache, which is
    a startup-built snapshot with no live DB reads. Without the reload the row is
    committed but invisible to the provider, so the team fetch silently resolves
    nothing and caches zero teams until the next restart or cache refresh.
    """
    with get_db() as conn:
        league = create_custom_league(conn, **fields)

    _reload_league_mappings()
    team_refresh = refresh_custom_league_teams(league["league_code"])
    return {**league, "team_refresh": team_refresh}


def _reload_league_mappings() -> None:
    """Reload the global league-mapping cache so a just-created league resolves.

    Best-effort: if the service isn't initialized (e.g. in unit tests that call
    the create path directly), there's nothing to reload and we move on.
    """

    try:
        get_league_mapping_service().reload()
    except RuntimeError:
        logger.debug("[CUSTOM_LEAGUE] Mapping service not initialized; skipping reload")
