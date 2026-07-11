"""Stream→event matching for event-group processing.

Covers matcher construction, the scoped EPG program index, feed-team
resolution and UFC/racing segment expansion of the matched-stream list.
"""

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, Any

from teamarr.consumers.matching import BatchMatchResult, StreamCategory, StreamMatcher
from teamarr.database.groups import EventEPGGroup
from teamarr.database.settings import get_feed_separation_settings
from teamarr.utilities.tz import get_user_timezone, to_utc

logger = logging.getLogger(__name__)


class StreamMatching:
    """Matches streams to events and shapes the matched-stream list.

    Mixin for EventGroupProcessor — relies on the coordinator's
    ``_db_factory``, ``_dispatcharr_client``, ``_service``,
    ``_shared_events`` and ``_generation`` attributes.
    """

    if TYPE_CHECKING:
        # Provided by the EventGroupProcessor coordinator / sibling mixins.
        # Declared for type-checkers only — no runtime effect.
        _db_factory: Any
        _dispatcharr_client: Any
        _service: Any
        _shared_events: Any
        _get_all_known_leagues: Any
        _load_sport_durations: Any

    def _match_streams(
        self,
        streams: list[dict],
        group: EventEPGGroup,
        target_date: date,
        stream_progress_callback: Callable | None = None,
        status_callback: Callable[[str], None] | None = None,
        resolved_leagues: list[str] | None = None,
    ) -> BatchMatchResult:
        """Match streams to events using StreamMatcher.

        Uses fingerprint cache - streams only need to be matched once
        unless stream name changes.

        All groups use subscription leagues for both search and include scope.

        Args:
            streams: List of stream dicts
            group: Event EPG group (contains leagues, custom regex, etc.)
            target_date: Date to match events for
            stream_progress_callback: Optional callback(current, total, stream_name, matched)
            status_callback: Optional callback(status_message) for status updates
            resolved_leagues: Pre-resolved leagues (subscription leagues)
        """
        # Load settings for event filtering
        with self._db_factory() as conn:
            row = conn.execute(
                "SELECT include_final_events, "
                "epg_xtream_fallback_enabled, epg_xtream_cache_hours, "
                "event_match_days_back, event_match_days_ahead, "
                "tennis_majors_only "
                "FROM settings WHERE id = 1"
            ).fetchone()
            include_final_events = (
                bool(row["include_final_events"]) if row else False
            )
            xtream_fallback = bool(row["epg_xtream_fallback_enabled"]) if row else False
            xtream_cache_hours = (row["epg_xtream_cache_hours"] if row else 24) or 24
            match_days_back = (row["event_match_days_back"] if row else 7) or 7
            match_days_ahead = (row["event_match_days_ahead"] if row else 3) or 3
            tennis_majors_only = bool(row["tennis_majors_only"]) if row else False

            # Load feed separation settings
            feed_settings = get_feed_separation_settings(conn)
            feed_home_terms = feed_settings.home_terms if feed_settings.enabled else None
            feed_away_terms = feed_settings.away_terms if feed_settings.enabled else None

        sport_durations = self._load_sport_durations_cached()

        # EPG program-data matching (epic 183.6): build a scoped program index
        # ONLY when this group opted in (group.epg_match_enabled). Default off →
        # epg_index is None → matcher behaves exactly as before.
        epg_index = self._build_epg_index(
            group, streams, target_date,
            match_days_back, match_days_ahead, xtream_fallback,
            xtream_cache_hours,
        )

        # Search all known leagues (broad match), include only subscribed.
        # This preserves legacy multi-league behavior: streams are matched
        # against all events (catches team-name-only streams), then filtered
        # to only include events from subscribed leagues.
        # Union league_cache with subscription to guarantee subscribed leagues
        # are always searched even if cache hasn't been refreshed yet.
        include_leagues = (
            resolved_leagues if resolved_leagues else group.leagues
        )
        search_leagues = list(set(self._get_all_known_leagues()) | set(include_leagues))

        matcher = StreamMatcher(
            service=self._service,
            db_factory=self._db_factory,
            group_id=group.id,
            search_leagues=search_leagues,
            include_leagues=include_leagues,
            include_final_events=include_final_events,
            sport_durations=sport_durations,
            generation=getattr(self, "_generation", None),  # Use shared generation if set
            custom_regex_teams=group.custom_regex_teams,
            custom_regex_teams_enabled=group.custom_regex_teams_enabled,
            custom_regex_date=group.custom_regex_date,
            custom_regex_date_enabled=group.custom_regex_date_enabled,
            custom_regex_month=group.custom_regex_month,
            custom_regex_month_enabled=group.custom_regex_month_enabled,
            custom_regex_day=group.custom_regex_day,
            custom_regex_day_enabled=group.custom_regex_day_enabled,
            custom_regex_time=group.custom_regex_time,
            custom_regex_time_enabled=group.custom_regex_time_enabled,
            custom_regex_league=group.custom_regex_league,
            custom_regex_league_enabled=group.custom_regex_league_enabled,
            custom_regex_fighters=group.custom_regex_fighters,
            custom_regex_fighters_enabled=group.custom_regex_fighters_enabled,
            custom_regex_event_name=group.custom_regex_event_name,
            custom_regex_event_name_enabled=group.custom_regex_event_name_enabled,
            shared_events=self._shared_events,  # Reuse events across groups in same run
            stream_timezone=group.stream_timezone,  # TZ for interpreting stream dates
            feed_home_terms=feed_home_terms,
            feed_away_terms=feed_away_terms,
            name_match_enabled=group.name_match_enabled,
            tennis_majors_only=tennis_majors_only,
            team_streams_enabled=group.team_streams_enabled,
            epg_index=epg_index,
        )

        result = matcher.match_all(
            streams,
            target_date,
            progress_callback=stream_progress_callback,
            status_callback=status_callback,
        )

        # Purge stale cache entries at end of match
        matcher.purge_stale()

        return result

    def _build_epg_index(
        self,
        group,
        streams: list[dict],
        target_date: date,
        match_days_back: int,
        match_days_ahead: int,
        xtream_fallback: bool = False,
        xtream_cache_hours: int = 24,
    ):
        """Build a scoped EPGProgramIndex for EPG matching, or None if disabled.

        Gated on: per-group opt-in + a connected Dispatcharr.

        A raw M3U stream's tvg_id is usually a different namespace from EPG
        program tvg_ids, so we resolve each candidate stream to its EPG-source
        tvg_id via a cascade (direct tvg_id -> curated channel epg_data_id ->
        strict name match; see epg_resolver). This does NOT require the stream to
        be pre-built into an EPG-linked Dispatcharr channel. Programs are fetched
        by the resolved tvg_id but indexed by the stream tvg_id for matcher
        lookup.
        """
        if not group.epg_match_enabled:
            return None
        if not self._dispatcharr_client:
            return None

        if not any(s.get("tvg_id") for s in streams):
            return None

        from datetime import datetime, time

        from teamarr.consumers.matching.epg_index import EPGProgramIndex
        from teamarr.consumers.matching.epg_resolver import resolve_program_tvg_ids

        # Resolve stream tvg_ids -> EPG-source tvg_ids. Needs the EPGData catalog
        # (for direct + name matching) and the stream->channel map (for the
        # curated channel fallback). Both are single scoped fetches.
        try:
            epg_data_list = self._dispatcharr_client.channels.get_epg_data_list()
            stream_channels = self._dispatcharr_client.channels.get_stream_channel_map()
        except Exception as e:
            logger.warning("[EPG-MATCH] Failed to load EPG resolution data: %s", e)
            return None

        # Direct/name matching must only use the ACTIVE imported EPG (curated
        # channel links are trusted regardless). _Teamarr (our own output) is
        # excluded so we never resolve a stream to our generated guide.
        active_source_ids = self._active_epg_source_ids()
        resolution, _stats = resolve_program_tvg_ids(
            streams, epg_data_list, stream_channels, active_source_ids=active_source_ids
        )

        # Window mirrors the event match window so programs overlapping any
        # candidate event are indexed. Localize to the user's timezone before
        # converting to UTC (to_utc rejects naive datetimes).
        day_start = datetime.combine(target_date, time.min, tzinfo=get_user_timezone())
        window_start = to_utc(day_start - timedelta(days=match_days_back))
        window_end = to_utc(day_start + timedelta(days=match_days_ahead + 1))

        try:
            index = (
                EPGProgramIndex.build(
                    self._dispatcharr_client.epg, resolution, window_start, window_end
                )
                if resolution
                else EPGProgramIndex({})
            )
        except Exception as e:
            logger.warning("[EPG-MATCH] Failed to build EPG index for group %s: %s", group.id, e)
            index = EPGProgramIndex({})

        # Cascade layer 4 (epic crs): for streams the curated DP guide produced
        # NO programs for (unresolved, or resolved to an empty mirror channel),
        # fall back to the provider's OWN xmltv when the group's M3U account is
        # Xtream. Source-matched, so the stream tvg_id IS the guide channel id.
        # Opt-in via the global epg_xtream_fallback_enabled setting.
        if xtream_fallback:
            self._add_xtream_epg_fallback(
                index, group, streams, window_start, window_end, xtream_cache_hours
            )

        if not index:
            logger.info("[EPG-MATCH] group=%s no programs indexed (DP guide + xtream)", group.id)
            return None
        logger.info(
            "[EPG-MATCH] group=%s indexed %d programs across %d tvg_ids",
            group.id, index.program_count(), len(index.tvg_ids()),
        )
        return index

    def _active_epg_source_ids(self) -> set[int] | None:
        """Enabled EPG-source ids for name/direct matching (excludes _Teamarr).

        Returns None on failure so the resolver falls back to the full catalog
        rather than matching nothing.
        """
        try:
            sources = self._dispatcharr_client.client.paginated_get(
                "/api/epg/sources/", error_context="epg sources"
            )
        except Exception as e:
            logger.debug("[EPG-MATCH] active-source lookup failed: %s", e)
            return None
        active = {
            s["id"]
            for s in sources
            if s.get("id") is not None and s.get("is_active") and s.get("name") != "_Teamarr"
        }
        return active or None

    def _add_xtream_epg_fallback(
        self, index, group, streams, window_start, window_end, cache_hours: int = 24
    ) -> None:
        """Fill EPG-index gaps from the group's Xtream provider's own xmltv (crs).

        No-op unless the group's M3U account is an Xtream panel. Fetches the
        provider's xmltv.php (cached) only for stream tvg_ids the DP guide left
        without programs, and merges them in (the curated guide keeps priority).
        Best-effort: any failure leaves the DP-built index untouched.
        """
        from teamarr.consumers.matching.epg_xtream import (
            fetch_xtream_programs,
            is_xtream_account,
            xmltv_url,
        )

        account_id = getattr(group, "m3u_account_id", None)
        if not account_id:
            return
        try:
            resp = self._dispatcharr_client.client.get(f"/api/m3u/accounts/{account_id}/")
            account = resp.json() if resp is not None and resp.status_code == 200 else None
        except Exception as e:
            logger.debug("[XTREAM-EPG] group=%s account fetch failed: %s", group.id, e)
            return
        if account is None or not is_xtream_account(account):
            return

        already = set(index.tvg_ids())
        wanted = {s.get("tvg_id") for s in streams if s.get("tvg_id")} - already
        if not wanted:
            return

        url = xmltv_url(account)
        if url is None:
            # Unreachable in practice — account already passed is_xtream_account,
            # which is xmltv_url's own precondition. Guard keeps the type sound.
            return
        programs = fetch_xtream_programs(
            url,
            cache_key=f"acct{account_id}",
            wanted_tvg_ids=wanted,
            window_start=window_start,
            window_end=window_end,
            ttl_seconds=max(1, cache_hours) * 3600,
        )
        if programs:
            added = index.merge(programs)
            logger.info(
                "[XTREAM-EPG] group=%s account=%s filled %d tvg_ids (%d programs) "
                "from provider xmltv for %d DP-unmatched streams",
                group.id, account_id, len(programs), added, len(wanted),
            )

    def _load_sport_durations_cached(self) -> dict[str, float]:
        """Load sport durations (cached for reuse within a run)."""
        if not hasattr(self, "_sport_durations_cache"):
            with self._db_factory() as conn:
                self._sport_durations_cache = self._load_sport_durations(conn)
        return self._sport_durations_cache

    def _build_matched_stream_list(
        self,
        streams: list[dict],
        match_result: BatchMatchResult,
        stream_timezone: str | None = None,
    ) -> list[dict]:
        """Build list of matched streams with their events.

        Returns list of dicts with 'stream' and 'event' keys.
        Also applies UFC segment expansion to create separate channels per segment.

        Args:
            streams: List of stream dicts
            match_result: Result from matcher
            stream_timezone: Group-configured timezone for stream time interpretation
        """
        # Look up by stream ID first: identically named streams (same provider,
        # multiple M3U logins) collapse in a name-keyed dict, silently dropping
        # all but one stream per name (#264). Name lookup is only a fallback.
        stream_by_id = {s["id"]: s for s in streams if s.get("id") is not None}
        stream_by_name = {s["name"]: s for s in streams}

        matched = []
        for result in match_result.results:
            if result.matched and result.included and result.event:
                stream = stream_by_id.get(result.stream_id) or stream_by_name.get(
                    result.stream_name
                )
                if stream:
                    matched.append(
                        {
                            "stream": stream,
                            "event": result.event,
                            "card_segment": result.card_segment,  # UFC segment from classifier
                            "feed_hint": result.feed_hint,  # "home", "away", or None
                            "match_type": (
                                "team" if result.category == StreamCategory.TEAM_ONLY else "event"
                            ),
                            # How the stream matched ('epg', 'fuzzy', …) for the
                            # epg_match stream-ordering rule.
                            "match_method": (
                                result.match_method.value if result.match_method else None
                            ),
                            # EPG time-windowing (183.5): program broadcast slot for
                            # MatchMethod.EPG matches; None for name matches (full-life).
                            "epg_program_start": result.epg_program_start,
                            "epg_program_end": result.epg_program_end,
                        }
                    )

        # Apply UFC segment expansion
        # This splits UFC streams into separate segment channels
        matched = self._expand_ufc_segments(matched, stream_timezone)

        # Apply racing session expansion
        # This splits racing streams into separate per-session channels
        matched = self._expand_racing_segments(matched)

        return matched

    def _resolve_feed_teams(
        self,
        matched_streams: list[dict],
        detect_team_names: bool,
    ) -> list[dict]:
        """Resolve feed hints to actual teams (Phase 2 feed separation).

        For each matched stream, in precedence order:
        - feed_hint="home"/"away" (explicit HOME/AWAY term) → that side's team
        - No hint → match the stream name against the event's home/away-market
          broadcast names (ESPN broadcasts[].market: 'Brewers.TV' → away,
          'YES' → home) — catches team-branded and regional channels no term
          list or team name covers (#343)
        - Still nothing + detect_team_names → scan stream name for team
          name/short_name in a feed-specific context
        - No match → feed_team = None (normal channel)

        Args:
            matched_streams: List of matched stream dicts with 'event', 'stream', 'feed_hint'
            detect_team_names: Whether to scan stream names for team name patterns
        """
        for entry in matched_streams:
            event = entry.get("event")
            feed_hint = entry.get("feed_hint")
            feed_team = None
            source = feed_hint

            if event and feed_hint == "home":
                feed_team = event.home_team
            elif event and feed_hint == "away":
                feed_team = event.away_team
            elif event and not feed_hint:
                stream_name = entry["stream"]["name"].lower()
                feed_team = self._detect_feed_from_broadcast_markets(stream_name, event)
                source = "broadcast_market"
                if feed_team is None and detect_team_names:
                    feed_team = self._detect_team_in_stream_name(
                        stream_name, event.home_team, event.away_team
                    )
                    source = "team_name_detect"

            entry["feed_team"] = feed_team

            if feed_team:
                logger.info(
                    "[FEED] Stream '%s' → feed_team=%s (hint=%s)",
                    entry["stream"]["name"][:50],
                    feed_team.name,
                    source,
                )

        return matched_streams

    @staticmethod
    def _detect_feed_from_broadcast_markets(stream_name_lower: str, event):
        """Match the stream name against the event's home/away-market
        broadcast names (ESPN broadcasts[].market, #343).

        'national' names never make a team feed; a stream matching BOTH
        sides' names is ambiguous and stays a normal channel. Names shorter
        than 3 characters are skipped (false-positive guard, same threshold
        as team abbreviations).
        """
        import re

        markets = getattr(event, "broadcast_markets", None) or {}
        matched_sides: set[str] = set()
        for name, market in markets.items():
            if market not in ("home", "away") or len(name) < 3:
                continue
            if re.search(rf"\b{re.escape(name.lower())}\b", stream_name_lower):
                matched_sides.add(market)

        if matched_sides == {"home"}:
            return event.home_team
        if matched_sides == {"away"}:
            return event.away_team
        return None

    @staticmethod
    def _detect_team_in_stream_name(
        stream_name_lower: str, home_team, away_team
    ):
        """Detect team-specific feed by looking for feed indicator patterns.

        Only matches when a team name appears in a feed-specific context:
        - In parentheses: "Game Title (Penguins)" or "(Penguins Feed)"
        - With feed keyword: "Penguins Feed", "Penguins Broadcast"
        - After pipe/dash at end: "Game | Penguins", "Game - Penguins"
        - With home/away: "Penguins Home", "Home Penguins"
        - Team-branded channel token: "Penguins.TV" (#343)

        Does NOT match team names that just appear in a matchup title like
        "Penguins vs Jets" — that's a shared feed, not team-specific.
        """
        import re

        def _get_candidates(t) -> list[str]:
            c = [t.name.lower()]
            if t.short_name and t.short_name.lower() != t.name.lower():
                c.append(t.short_name.lower())
            if t.abbreviation and len(t.abbreviation) >= 3:
                c.append(t.abbreviation.lower())
            return c

        home_candidates = _get_candidates(home_team)
        away_candidates = _get_candidates(away_team)

        for team, candidates, other_candidates in [
            (home_team, home_candidates, away_candidates),
            (away_team, away_candidates, home_candidates),
        ]:
            for candidate in candidates:
                esc = re.escape(candidate)
                # Team in parentheses: "(Penguins)" or "(Penguins Feed)"
                if re.search(rf"\(\s*{esc}(?:\s+feed)?\s*\)", stream_name_lower):
                    return team

                patterns = [
                    rf"\b{esc}\s+(?:feed|broadcast)\b",
                    rf"\b(?:feed|broadcast)[:\s]+{esc}\b",
                    rf"\b{esc}\s+(?:home|away)\b",
                    rf"\b(?:home|away)\s+{esc}\b",
                    # Team-branded channel token: "Brewers.TV" (#343)
                    rf"\b{esc}\.tv\b",
                ]

                for pattern in patterns:
                    for match in re.finditer(pattern, stream_name_lower):
                        remainder = stream_name_lower[match.end():]

                        # Skip when the opposing team is named *after* the feed
                        # keyword — that's a shared matchup feed ("4K FEED A B"),
                        # not a team-specific feed.
                        other_team_after = any(
                            re.search(rf"\b{re.escape(other)}\b", remainder)
                            for other in other_candidates
                        )

                        if not other_team_after:
                            return team

        return None

    def _expand_ufc_segments(
        self, matched_streams: list[dict], stream_timezone: str | None = None
    ) -> list[dict]:
        """Expand UFC streams into segment-based channels.

        Groups UFC streams by detected segment (early_prelims, prelims, main_card)
        and creates separate channel entries for each. Non-UFC streams pass through.

        Args:
            matched_streams: List of {'stream': ..., 'event': ...} dicts
            stream_timezone: Group-configured timezone for stream time interpretation

        Returns:
            Expanded list with UFC streams grouped by segment
        """
        from teamarr.consumers.ufc_segments import expand_ufc_segments

        sport_durations = self._load_sport_durations_cached()
        return expand_ufc_segments(matched_streams, sport_durations, stream_timezone)

    def _expand_racing_segments(self, matched_streams: list[dict]) -> list[dict]:
        """Expand racing streams into session-based channels.

        Splits each matched racing stream into one entry per race-weekend
        session (Practice 1, Qualifying, Race, ...) using ESPN session data.
        Non-racing streams pass through.

        Args:
            matched_streams: List of {'stream': ..., 'event': ...} dicts

        Returns:
            Expanded list with racing streams split by session
        """
        from teamarr.consumers.racing_segments import expand_racing_segments

        sport_durations = self._load_sport_durations_cached()
        return expand_racing_segments(matched_streams, sport_durations)

    def _enrich_matched_events(self, matched_streams: list[dict]) -> list[dict]:
        """Enrich all matched events with fresh status from provider.

        Fetches fresh event data from summary endpoint for each matched event.
        This ensures lifecycle filtering uses current final status, not stale
        cached status from scoreboard/schedule.

        Args:
            matched_streams: List of {'stream': ..., 'event': ...} dicts

        Returns:
            Same list with events replaced by enriched versions
        """
        if not matched_streams:
            return matched_streams

        enriched = []
        for match in matched_streams:
            event = match.get("event")
            if event:
                old_status = event.status.state if event.status else "N/A"
                # Refresh event status from provider. The service coalesces
                # repeated refreshes of the same event within a run, so an event
                # matched to many channels triggers a single provider fetch.
                refreshed = self._service.refresh_event_status(event)
                new_status = refreshed.status.state if refreshed.status else "N/A"
                if old_status != new_status:
                    logger.debug(
                        "[ENRICH] event=%s status changed: %s → %s",
                        event.id,
                        old_status,
                        new_status,
                    )
                # Preserve all keys (including segment info for UFC)
                enriched_match = dict(match)
                enriched_match["event"] = refreshed
                enriched.append(enriched_match)
            else:
                enriched.append(match)

        logger.debug("[EVENT_EPG] Enriched %d matched events with fresh status", len(enriched))
        return enriched

    def _sort_matched_streams(
        self,
        matched_streams: list[dict],
        sort_order: str = "sport_league_time",
    ) -> list[dict]:
        """Sort matched streams by sport → league → time → event_id.

        Fixed sort order in v59 — always sport_league_time.
        The sort_order parameter is kept for API compatibility but ignored.

        Args:
            matched_streams: List of {'stream': ..., 'event': ...} dicts
            sort_order: Ignored (always sport_league_time)

        Returns:
            Sorted list of matched streams
        """
        if not matched_streams:
            return matched_streams

        max_time = datetime.max.replace(tzinfo=None)

        def sort_key(m: dict):
            event = m.get("event")
            if not event:
                return ("zzz", "zzz", max_time, "")
            sport = event.sport.lower() if event.sport else "zzz"
            league = event.league.lower() if event.league else "zzz"
            start = event.start_time
            if start and start.tzinfo:
                start = start.replace(tzinfo=None)
            event_id = str(getattr(event, "id", ""))
            return (sport, league, start or max_time, event_id)

        return sorted(matched_streams, key=sort_key)
