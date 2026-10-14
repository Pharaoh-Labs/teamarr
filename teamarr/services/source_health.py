"""Evidence-based review recommendations for configured event sources.

This is deliberately advisory: user-owned sources are never disabled or
deleted here. Missing M3U groups remain the responsibility of the existing
stale-source/rebind flow.
"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from sqlite3 import Connection
from typing import Any

from teamarr.database.groups import EventEPGGroup, get_all_groups, get_stale_groups
from teamarr.utilities.tz import now_utc, parse_db_timestamp, to_db_utc

# Broad, recurring activity windows. They include preseason/playoffs to avoid
# treating those useful feeds as dormant. Positive provider event data can
# override the calendar, and unknown leagues are never assumed active without it.
_SEASON_WINDOWS: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {
    "nfl": ((8, 1), (2, 28)),
    "nhl": ((9, 1), (6, 30)),
    "mlb": ((2, 15), (11, 15)),
}

RUN_HISTORY_DAYS = 30
RECENT_LEAGUE_ACTIVITY_DAYS = 21
EVENT_ACTIVITY_LOOKAHEAD_DAYS = 30
SEASON_START_GRACE_DAYS = 21
MIN_QUIET_DAYS = 45
MIN_NEVER_MATCHED_DAYS = 60
MIN_RELEVANT_RUNS = 5
MIN_RUN_SPAN_DAYS = 14
MIN_ELIGIBLE_STREAMS = 20
LOW_COVERAGE_THRESHOLD = 0.10
SNOOZE_DAYS = 30


def _season_bounds(league: str, today: date) -> tuple[date, date] | None:
    window = _SEASON_WINDOWS.get(league.lower())
    if window is None:
        return None
    (start_month, start_day), (end_month, end_day) = window
    wraps_year = (start_month, start_day) > (end_month, end_day)

    if wraps_year and (today.month, today.day) <= (end_month, end_day):
        start_year = today.year - 1
    else:
        start_year = today.year
    end_year = start_year + int(wraps_year)
    try:
        return date(start_year, start_month, start_day), date(end_year, end_month, end_day)
    except ValueError:
        # Feb 29 is deliberately not used in the configured windows, but keep
        # malformed future profiles from taking down the Sources page.
        return None


def league_season_active(
    league: str,
    today: date,
    recently_active: set[str] | None = None,
) -> bool | None:
    """Return True/False when known, None when seasonality is unknown.

    A league with a positive recent provider event observation is active even
    if its broad fallback window says otherwise (e.g. a rescheduled playoff).
    """
    code = league.lower()
    if code in (recently_active or set()):
        return True
    bounds = _season_bounds(code, today)
    if bounds is None:
        return None
    start, end = bounds
    if not start <= today <= end:
        return False
    return today >= start + timedelta(days=SEASON_START_GRACE_DAYS)


def managed_source_idle_days(
    last_matched_at: str | datetime | None,
    created_at: str | datetime | None,
    focus_leagues: list[str],
    now: datetime,
    recently_active: set[str],
    activity_starts: dict[str, date] | None = None,
) -> float | None:
    """Return in-season idle days for discovery retirement, else ``None``.

    Unknown league scope and offseason both pause automatic retirement. The
    clock starts after a 21-day season-opening grace period, so a stale match
    from last season cannot immediately retire a source when the next season
    begins. Every scoped league must have known season state; recent positive
    provider event evidence establishes state for unknown calendars.
    """
    normalized = sorted({code.lower() for code in focus_leagues if code})
    if not normalized or not (set(normalized) & recently_active):
        return None
    statuses = {
        code: league_season_active(code, now.date(), recently_active) for code in normalized
    }
    if any(status is None for status in statuses.values()):
        return None
    active = [code for code, is_active in statuses.items() if is_active]
    if not active:
        return None

    activity_starts = activity_starts or {}
    eligible_starts = []
    for code in active:
        bounds = _season_bounds(code, now.date())
        if bounds is not None and bounds[0] <= now.date() <= bounds[1]:
            opportunity_start = bounds[0]
        else:
            # Unknown-calendar leagues (or a league with current schedule
            # activity outside its broad calendar window) use observed event
            # dates. This preserves the opening grace without disabling them
            # forever merely because they have no hard-coded season profile.
            opportunity_start = activity_starts.get(code)
        if opportunity_start is not None:
            eligible_starts.append(opportunity_start + timedelta(days=SEASON_START_GRACE_DAYS))
    if not eligible_starts:
        return None
    season_opportunity_start = min(eligible_starts)
    last_match = _as_datetime(last_matched_at)
    created = _as_datetime(created_at)
    reference = last_match or created
    if reference is None:
        return None
    effective_start = max(reference.date(), season_opportunity_start)
    return max(0.0, (now.date() - effective_start).total_seconds() / 86400)


def _as_datetime(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=now_utc().tzinfo)
        return value
    try:
        return parse_db_timestamp(value)
    except (TypeError, ValueError):
        return None


def _load_run_observations(
    conn: Connection, now: datetime
) -> tuple[dict[int, list[dict[str, Any]]], dict[str, set[date]]]:
    """Read bounded per-source summaries from successful full generation runs."""
    cutoff = to_db_utc(now - timedelta(days=RUN_HISTORY_DAYS))
    rows = conn.execute(
        """SELECT completed_at, extra_metrics
           FROM processing_runs
           WHERE run_type = 'full_epg' AND status = 'completed'
             AND completed_at >= ? AND completed_at <= ?
           ORDER BY completed_at""",
        (cutoff, to_db_utc(now)),
    ).fetchall()
    by_group: dict[int, list[dict[str, Any]]] = defaultdict(list)
    activity_dates: dict[str, set[date]] = defaultdict(set)
    for row in rows:
        try:
            completed_at = parse_db_timestamp(row["completed_at"])
            metrics = json.loads(row["extra_metrics"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if completed_at is None or not isinstance(metrics, dict):
            continue
        for summary in metrics.get("groups", []):
            if (
                not isinstance(summary, dict)
                or summary.get("error")
                or summary.get("provider_fetch_failures", 0)
            ):
                continue
            try:
                group_id = int(summary["id"])
                fetched = max(0, int(summary.get("fetched", 0)))
                eligible = max(0, int(summary.get("eligible", 0)))
                matched = max(0, int(summary.get("matched", 0)))
            except (KeyError, TypeError, ValueError):
                continue
            leagues_raw = summary.get("matched_leagues", {})
            leagues: dict[str, int] = {}
            if isinstance(leagues_raw, dict):
                for code, count in leagues_raw.items():
                    try:
                        normalized = str(code).strip().lower()
                        amount = max(0, int(count))
                    except (TypeError, ValueError):
                        continue
                    if normalized and amount:
                        leagues[normalized] = amount
            by_group[group_id].append(
                {
                    "completed_at": completed_at,
                    "fetched": fetched,
                    "eligible": eligible,
                    "matched": matched,
                    "matched_leagues": leagues,
                    "matching_types": summary.get("matching_types") or {},
                }
            )
        event_dates_raw = metrics.get("observed_event_dates", {})
        if isinstance(event_dates_raw, dict):
            for code, values in event_dates_raw.items():
                normalized = str(code).strip().lower()
                if not normalized or not isinstance(values, list):
                    continue
                for value in values:
                    try:
                        activity_dates[normalized].add(date.fromisoformat(str(value)))
                    except (TypeError, ValueError):
                        continue
    return by_group, activity_dates


def recently_observed_leagues(conn: Connection, now: datetime | None = None) -> set[str]:
    """League codes with positive, dated event data in successful generations."""
    leagues, _ = league_activity_evidence(conn, now)
    return leagues


def league_activity_evidence(
    conn: Connection, now: datetime | None = None
) -> tuple[set[str], dict[str, date]]:
    """Return active leagues and the start of their current activity streak."""
    now = now or now_utc()
    _, activity_dates = _load_run_observations(conn, now)
    oldest = now.date() - timedelta(days=RECENT_LEAGUE_ACTIVITY_DAYS)
    latest = now.date() + timedelta(days=EVENT_ACTIVITY_LOOKAHEAD_DAYS)
    starts: dict[str, date] = {}
    for code, event_dates in activity_dates.items():
        current_dates = [event_date for event_date in event_dates if oldest <= event_date <= latest]
        if current_dates:
            starts[code] = min(current_dates)
    activity_cutoff = now - timedelta(days=RECENT_LEAGUE_ACTIVITY_DAYS)
    for row in conn.execute(
        "SELECT league_code, activity_started_at, last_observed_at FROM league_event_activity"
    ):
        try:
            last_observed = parse_db_timestamp(row["last_observed_at"])
            started = parse_db_timestamp(row["activity_started_at"])
        except (TypeError, ValueError):
            continue
        if last_observed is None or last_observed < activity_cutoff or started is None:
            continue
        code = str(row["league_code"]).strip().lower()
        if code:
            starts[code] = started.date()
    return set(starts), starts


def _named_leagues(group: EventEPGGroup, surfaces: dict[str, set[str]]) -> list[str]:
    """Use configured league names/aliases as source-specific scope evidence."""
    # Reuse discovery's data-driven matcher; unlike a hard-coded alias list,
    # this follows league names already present in the database.
    from teamarr.consumers.source_lifecycle.discovery import leagues_named_by

    text = " ".join(
        value for value in (group.name, group.display_name, group.m3u_group_name) if value
    )
    return leagues_named_by(text, surfaces)


def _configured_leagues(
    group: EventEPGGroup,
    inherited_leagues: set[str],
    enabled_soccer: set[str],
    soccer_team_leagues: dict[tuple[str, str], set[str]],
) -> set[str]:
    """Resolve a source override without re-reading shared subscription data."""
    if group.subscription_leagues is None:
        base_leagues = inherited_leagues
        soccer_mode = None
        followed_teams = None
    else:
        base_leagues = {code.lower() for code in group.subscription_leagues if code}
        soccer_mode = group.subscription_soccer_mode
        followed_teams = group.subscription_soccer_followed_teams

    codes = set(base_leagues)
    if soccer_mode == "all":
        codes = (codes - enabled_soccer) | enabled_soccer
    elif soccer_mode == "teams" and followed_teams:
        for team in followed_teams:
            provider = str(team.get("provider", "espn"))
            team_id = str(team.get("team_id") or "")
            if not team_id:
                continue
            codes.update(soccer_team_leagues.get((provider, team_id), set()))
    return codes


def _focus_leagues(
    group: EventEPGGroup,
    surfaces: dict[str, set[str]],
    inherited_leagues: set[str],
    enabled_soccer: set[str],
    soccer_team_leagues: dict[tuple[str, str], set[str]],
) -> list[str]:
    observed = {code.lower() for code in group.last_matched_leagues if code}
    named = {code.lower() for code in _named_leagues(group, surfaces) if code}
    configured = _configured_leagues(group, inherited_leagues, enabled_soccer, soccer_team_leagues)
    if group.subscription_leagues is not None:
        return sorted(observed | named | configured)
    # Inherited global scope is deliberately only a fallback. A source-specific
    # name or actual match history is narrower and must not bleed another
    # subscribed league's season into this group's review.
    specific = observed | named
    return sorted(specific if specific else inherited_leagues)


def _season_state(
    focus_leagues: list[str], today: date, recently_active: set[str]
) -> tuple[bool | None, list[str], date | None]:
    """Return (active, active league codes, earliest active-season start).

    At least one known active league is enough for a mixed source. Unknown
    leagues prevent a source from being called offseason when every known
    league is quiet.
    """
    if not focus_leagues:
        return None, [], None
    statuses = {code: league_season_active(code, today, recently_active) for code in focus_leagues}
    active = sorted(code for code, status in statuses.items() if status is True)
    if active:
        starts = []
        for code in active:
            bounds = _season_bounds(code, today)
            if bounds is not None and bounds[0] <= today <= bounds[1]:
                starts.append(bounds[0])
        return True, active, min(starts) if starts else None
    if any(status is None for status in statuses.values()):
        return None, [], None
    return False, [], None


def _days_since(value: str | datetime | None, now: datetime) -> int | None:
    if value is None:
        return None
    parsed = parse_db_timestamp(value.isoformat() if isinstance(value, datetime) else value)
    if parsed is None:
        return None
    return max(0, int((now - parsed).total_seconds() // 86400))


def _decision_is_hidden(decision: Any, group: EventEPGGroup, now: datetime) -> bool:
    if not decision:
        return False
    if decision["decision"] == "keep":
        return decision["baseline_last_matched_at"] == group.last_matched_at
    until = parse_db_timestamp(decision["snoozed_until"]) if decision["snoozed_until"] else None
    return until is not None and until > now


def _recommendation(
    group: EventEPGGroup,
    surfaces: dict[str, set[str]],
    runs: list[dict[str, Any]],
    today: date,
    now: datetime,
    recently_active: set[str],
    inherited_leagues: set[str],
    enabled_soccer: set[str],
    soccer_team_leagues: dict[tuple[str, str], set[str]],
) -> dict[str, Any] | None:
    focus = _focus_leagues(group, surfaces, inherited_leagues, enabled_soccer, soccer_team_leagues)
    active, active_leagues, season_start = _season_state(focus, today, recently_active)
    if active is not True:
        # Unknown activity is not evidence of a bad source. Provider event
        # observations can establish activity without requiring this source (or
        # a second source) to have matched a stream.
        return None

    relevant_runs = [
        run
        for run in runs
        if run["completed_at"].date() >= (season_start or today - timedelta(days=RUN_HISTORY_DAYS))
        and run["fetched"] > 0
        and run["eligible"] > 0
    ]
    if len(relevant_runs) < MIN_RELEVANT_RUNS:
        return None
    span_days = (
        relevant_runs[-1]["completed_at"].date() - relevant_runs[0]["completed_at"].date()
    ).days
    if span_days < MIN_RUN_SPAN_DAYS:
        return None

    last_match_days = _days_since(group.last_matched_at, now)
    never_matched_days = _days_since(group.created_at, now)
    if last_match_days is None:
        quiet_since = never_matched_days
        threshold = MIN_NEVER_MATCHED_DAYS
    else:
        quiet_since = last_match_days
        threshold = MIN_QUIET_DAYS
    # Do not count a known offseason toward the current season's quiet streak.
    if season_start is not None:
        active_season_days = max(0, (now.date() - season_start).days)
        quiet_since = min(quiet_since, active_season_days) if quiet_since is not None else None

    aggregate_eligible = sum(run["eligible"] for run in relevant_runs)
    aggregate_matched = sum(run["matched"] for run in relevant_runs)
    latest = relevant_runs[-1]
    base = {
        "group_id": group.id,
        "group_name": group.display_name or group.name,
        "kind": "quiet",
        "leagues": active_leagues,
        "last_matched_at": group.last_matched_at,
        "eligible_observations": aggregate_eligible,
        "matched_observations": aggregate_matched,
        "sample_runs": len(relevant_runs),
        "sample_days": span_days,
        "matching_types": latest["matching_types"],
        "coverage": None,
    }

    if quiet_since is not None and quiet_since >= threshold:
        base["reason"] = (
            f"No streams matched for {last_match_days} days"
            if last_match_days is not None
            else "This source has never matched a stream"
        )
        return base

    # Coverage only means something for name-based event feeds. Team and EPG
    # sources fan one stream out to many events and use different health signals.
    if (
        not group.name_match_enabled
        or aggregate_eligible < MIN_ELIGIBLE_STREAMS
        or aggregate_matched <= 0
    ):
        return None
    coverage = aggregate_matched / aggregate_eligible
    if coverage >= LOW_COVERAGE_THRESHOLD:
        return None
    base.update(
        kind="low_coverage",
        reason=(
            f"Only {aggregate_matched} of {aggregate_eligible} eligible stream observations "
            "matched "
            f"across {len(relevant_runs)} recent runs"
        ),
        coverage=coverage,
    )
    return base


def get_source_health(
    conn: Connection,
    *,
    now: datetime | None = None,
    include_hidden: bool = False,
) -> dict[str, Any]:
    """Return conservative source-review recommendations and hidden counts."""
    now = now or now_utc()
    observations, _ = _load_run_observations(conn, now)
    recently_active, _ = league_activity_evidence(conn, now)
    groups = get_all_groups(conn, include_disabled=True)
    missing_ids = {item["id"] for item in get_stale_groups(conn)}
    from teamarr.consumers.source_lifecycle.discovery import league_name_surfaces
    from teamarr.database.groups import get_enabled_soccer_leagues
    from teamarr.database.subscription import get_subscription

    league_codes = [row[0] for row in conn.execute("SELECT league_code FROM leagues") if row[0]]
    surfaces = league_name_surfaces(conn, league_codes)
    subscription = get_subscription(conn)
    enabled_soccer = {code.lower() for code in get_enabled_soccer_leagues(conn)}
    soccer_team_leagues: dict[tuple[str, str], set[str]] = defaultdict(set)
    for row in conn.execute(
        "SELECT provider_team_id, provider, league FROM team_cache WHERE sport = 'soccer'"
    ):
        soccer_team_leagues[(row["provider"], row["provider_team_id"])].add(row["league"].lower())
    inherited_leagues = _configured_leagues(
        EventEPGGroup(
            id=0,
            name="",
            subscription_leagues=subscription.leagues,
            subscription_soccer_mode=subscription.soccer_mode,
            subscription_soccer_followed_teams=subscription.soccer_followed_teams,
        ),
        set(),
        enabled_soccer,
        soccer_team_leagues,
    )
    decisions = {
        row["group_id"]: row
        for row in conn.execute("SELECT * FROM source_health_decisions").fetchall()
    }
    recommendations = []
    hidden_count = 0
    for group in groups:
        if not group.enabled or group.is_channel_source or group.id in missing_ids:
            continue
        candidate = _recommendation(
            group,
            surfaces,
            observations.get(group.id, []),
            now.date(),
            now,
            recently_active,
            inherited_leagues,
            enabled_soccer,
            soccer_team_leagues,
        )
        if candidate is None:
            continue
        decision = decisions.get(group.id)
        hidden = _decision_is_hidden(decision, group, now)
        candidate["decision"] = decision["decision"] if decision is not None and hidden else None
        if hidden:
            hidden_count += 1
            if not include_hidden:
                continue
        recommendations.append(candidate)
    recommendations.sort(
        key=lambda item: (
            item["kind"] != "quiet",
            -(item["sample_runs"]),
            item["group_name"].lower(),
        )
    )
    return {
        "window_days": RUN_HISTORY_DAYS,
        "recommendations": recommendations,
        "hidden_count": hidden_count,
    }
