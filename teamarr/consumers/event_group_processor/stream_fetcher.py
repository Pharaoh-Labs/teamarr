"""Stream fetching/filtering and provider event fetching for event groups."""

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta
from typing import TYPE_CHECKING, Any

from teamarr.core import Event
from teamarr.database.groups import EventEPGGroup
from teamarr.services.stream_filter import FilterResult, StreamFilter, StreamFilterConfig

logger = logging.getLogger(__name__)

# Number of parallel workers for event fetching
# Configurable via ESPN_MAX_WORKERS for users with DNS throttling (PiHole, AdGuard)
MAX_WORKERS = int(os.environ.get("ESPN_MAX_WORKERS", 100))


class StreamFetcher:
    """Fetches M3U streams from Dispatcharr and events from data providers.

    Mixin for EventGroupProcessor — relies on the coordinator's
    ``_db_factory``, ``_dispatcharr_client`` and ``_service`` attributes.
    """

    if TYPE_CHECKING:
        # Provided by the EventGroupProcessor coordinator / sibling mixins.
        # Declared for type-checkers only — no runtime effect.
        _db_factory: Any
        _dispatcharr_client: Any
        _service: Any
        _active_epg_source_ids: Any

    def _account_names(self) -> dict[int, str]:
        """Map M3U account id → name, cached per processor instance.

        Streams from Dispatcharr carry only ``m3u_account_id``; the display
        name must be resolved here so identically named streams from multiple
        logins are attributed to their OWN account (#297) — falling back to the
        group's single configured account name mislabels every stream in the
        group and mis-evaluates m3u-type stream-ordering rules.
        """
        cache = getattr(self, "_account_name_cache", None)
        if cache is None:
            try:
                accounts = self._dispatcharr_client.m3u.list_accounts(include_custom=True)
                cache = {a.id: a.name for a in accounts}
            except Exception as e:
                logger.warning("[EVENT_EPG] Failed to list M3U accounts: %s", e)
                cache = {}
            self._account_name_cache = cache
        return cache

    def _fetch_streams(self, group: EventEPGGroup) -> list[dict]:
        """Fetch M3U streams from Dispatcharr for the group.

        Uses group's m3u_group_id to filter streams. The system-managed
        channel-source group (183.9) instead draws its candidates from the
        streams curated onto Dispatcharr channels.
        """
        if not self._dispatcharr_client:
            logger.warning("[EVENT_EPG] Dispatcharr not configured - cannot fetch streams")
            return []

        if getattr(group, "is_channel_source", False):
            return self._fetch_channel_source_streams()

        try:
            m3u_manager = self._dispatcharr_client.m3u

            # Fetch streams filtered by M3U group if configured
            if group.m3u_group_id:
                streams = m3u_manager.list_streams(group_id=group.m3u_group_id)
            else:
                # Fetch all streams if no group filter
                streams = m3u_manager.list_streams()

            # Convert to dicts for matcher (sorted by name for consistent order)
            account_names = self._account_names()
            stream_dicts = [
                {
                    "id": s.id,
                    "name": s.name,
                    "tvg_id": s.tvg_id,
                    "tvg_name": s.tvg_name,
                    "channel_group": s.channel_group,
                    "channel_group_id": s.channel_group_id,
                    "m3u_account_id": s.m3u_account_id,
                    "m3u_account_name": account_names.get(s.m3u_account_id),
                    "is_stale": s.is_stale,
                }
                for s in streams
            ]
            # Sort by stream ID ascending for consistent processing order
            stream_dicts.sort(key=lambda s: s["id"])
            return stream_dicts

        except Exception as e:
            logger.error("[EVENT_EPG] Failed to fetch streams: %s", e)
            return []

    def _fetch_channel_source_streams(self) -> list[dict]:
        """Build EPG-match candidates from streams curated onto Dispatcharr channels.

        Epic 183.9. For each Dispatcharr channel that (a) carries an active,
        non-``_Teamarr`` EPG link and (b) is NOT one of Teamarr's own managed
        output channels, emit a candidate per assigned stream tagged with the
        CHANNEL's own EPG ``tvg_id`` — so the existing resolver/index path matches
        that channel's programs to events and attaches its streams. Teamarr's
        channels are OUTPUT, not INPUT, so they are excluded.
        """
        client = self._dispatcharr_client
        try:
            stream_channel_map = client.channels.get_stream_channel_map()
            epg_data_list = client.channels.get_epg_data_list()
        except Exception as e:
            logger.warning("[CHANNEL_SOURCE] Failed to load channel/EPG data: %s", e)
            return []

        active_source_ids = self._active_epg_source_ids()
        epg_by_id = {e["id"]: e for e in epg_data_list if e.get("id") is not None}

        # Teamarr's own managed channels are OUTPUT — never treat them as a source.
        # Also collect the M3U group ids already covered by an EPG-match-enabled
        # group: streams in those groups are matched by the per-group path (whose
        # tier-1 resolution uses the same channel EPG), so including them here would
        # double-process the identical match. Consolidation would dedupe the result
        # anyway, but skipping avoids wasted work and inflated source-group stats.
        managed_ids: set[int] = set()
        epg_group_m3u_ids: set[int] = set()
        # User-selected DP channel groups to scope the scan (ybt.2). Empty = all.
        # Scoping skips the expensive EPG-resolution/matching for channels in
        # groups the user didn't pick — a generation-time saving.
        selected_groups: set[int] = set()
        try:
            from teamarr.database.channels import get_all_managed_channels
            from teamarr.database.groups import get_all_groups
            from teamarr.database.settings import get_epg_settings

            with self._db_factory() as conn:
                managed_ids = {
                    mc.dispatcharr_channel_id
                    for mc in get_all_managed_channels(conn, include_deleted=False)
                    if mc.dispatcharr_channel_id
                }
                epg_group_m3u_ids = {
                    g.m3u_group_id
                    for g in get_all_groups(conn, include_disabled=False)
                    if g.epg_match_enabled and not g.is_channel_source and g.m3u_group_id
                }
                selected_groups = {
                    int(gid) for gid in get_epg_settings(conn).epg_channel_source_groups
                }
        except Exception as e:
            logger.warning("[CHANNEL_SOURCE] Failed to load managed/group ids: %s", e)

        # Stream detail (name, account) keyed by id — listed once.
        try:
            detail_by_id = {s.id: s for s in client.m3u.list_streams()}
        except Exception as e:
            logger.warning("[CHANNEL_SOURCE] Failed to list streams: %s", e)
            detail_by_id = {}

        candidates: list[dict] = []
        seen: set[int] = set()
        skipped_teamarr = 0
        skipped_overlap = 0
        skipped_group = 0
        for stream_id, ch in stream_channel_map.items():
            if ch.get("id") in managed_ids:
                skipped_teamarr += 1
                continue
            # Scope to user-selected DP channel groups (ybt.2). Checked early so we
            # skip the EPG lookups/matching for undesired groups entirely.
            dp_group_id = ch.get("channel_group_id")
            if selected_groups and dp_group_id not in selected_groups:
                skipped_group += 1
                continue
            eid = ch.get("effective_epg_data_id") or ch.get("epg_data_id")
            ed = epg_by_id.get(eid)
            if not ed or not ed.get("tvg_id"):
                continue
            if active_source_ids is not None and ed.get("epg_source") not in active_source_ids:
                continue
            if stream_id in seen:
                continue
            detail = detail_by_id.get(stream_id)
            # Dedupe: an EPG-match-enabled M3U group already handles this stream.
            if (
                epg_group_m3u_ids
                and detail is not None
                and getattr(detail, "channel_group_id", None) in epg_group_m3u_ids
            ):
                skipped_overlap += 1
                continue
            seen.add(stream_id)
            account_id = getattr(detail, "m3u_account_id", None) if detail else None
            candidates.append(
                {
                    "id": stream_id,
                    "name": (getattr(detail, "name", None) if detail else None)
                    or ch.get("name")
                    or "",
                    # Tag with the channel's own EPG tvg_id so resolve/index use its guide.
                    "tvg_id": ed["tvg_id"],
                    "tvg_name": getattr(detail, "tvg_name", None) if detail else None,
                    "channel_group": getattr(detail, "channel_group", None) if detail else None,
                    "channel_group_id": getattr(detail, "channel_group_id", None)
                    if detail
                    else None,
                    # The DP CHANNEL's own group (channel organization), distinct from
                    # the M3U stream group above — drives scoping + the sorting rule.
                    "dp_channel_group_id": dp_group_id,
                    "dp_channel_group": ch.get("channel_group_name"),
                    "m3u_account_id": account_id,
                    "m3u_account_name": self._account_names().get(account_id)
                    if account_id is not None
                    else None,
                    "is_stale": getattr(detail, "is_stale", False) if detail else False,
                }
            )

        candidates.sort(key=lambda s: s["id"])
        logger.info(
            "[CHANNEL_SOURCE] built %d candidate stream(s) from curated DP channels "
            "(excluded %d Teamarr-managed, %d already in EPG-match groups, "
            "%d outside selected groups)",
            len(candidates),
            skipped_teamarr,
            skipped_overlap,
            skipped_group,
        )
        return candidates

    def _filter_streams(
        self,
        streams: list[dict],
        group: EventEPGGroup,
    ) -> tuple[list[dict], FilterResult]:
        """Filter streams using global settings and group's regex configuration.

        Global settings apply first (event pattern filter), then group-specific.

        Args:
            streams: List of stream dicts from Dispatcharr
            group: Event group with filter configuration

        Returns:
            Tuple of (filtered_streams, filter_result)
        """
        from teamarr.database.settings import get_stream_filter_settings

        # Load global stream filter settings
        with self._db_factory() as conn:
            global_settings = get_stream_filter_settings(conn)

        # Build config combining global and group settings
        config = StreamFilterConfig(
            # Global event pattern filter (enabled by default)
            require_event_pattern=global_settings.require_event_pattern,
            # Group-specific include regex (if enabled)
            include_regex=group.stream_include_regex,
            include_enabled=group.stream_include_regex_enabled,
            # Group-specific exclude regex (if enabled)
            exclude_regex=group.stream_exclude_regex,
            exclude_enabled=group.stream_exclude_regex_enabled,
            # Group-specific team extraction
            custom_teams_regex=group.custom_regex_teams,
            custom_teams_enabled=group.custom_regex_teams_enabled,
            # team_streams_enabled and epg_match_enabled both implicitly skip builtin
            # filtering — team-branded streams ("NHL | Maple Leafs") and static-named
            # linear channels ("ESPN", "NBA1") have no vs/@ separator and would
            # otherwise be rejected by the placeholder/event-pattern filter before the
            # matcher ever sees them. EPG matching needs those linear streams to survive
            # so it can match them via program data. The classifier/matcher gate what
            # actually matches, so passing extra streams through is harmless.
            skip_builtin=(
                group.skip_builtin_filter
                or group.team_streams_enabled
                or group.epg_match_enabled
                # When Stream Name matching is off, the built-in "must contain
                # vs/@/at" pre-filter would wrongly drop the team/linear streams
                # the active types (Team/EPG) rely on — bypass it.
                or not group.name_match_enabled
            ),
            team_streams_enabled=group.team_streams_enabled,
        )

        stream_filter = StreamFilter(config)
        result = stream_filter.filter(streams)

        # Log filtering results
        filtered_total = (
            result.filtered_stale
            + result.filtered_placeholder
            + result.filtered_unsupported_sport
            + result.filtered_not_event
            + result.filtered_include
            + result.filtered_exclude
        )
        if filtered_total > 0:
            logger.info(
                "[FILTER] Group '%s': %d input → %d passed "
                "(stale: -%d, placeholder: -%d, unsupported_sport: -%d, not_event: -%d, "
                "include: -%d, exclude: -%d)",
                group.name,
                result.total_input,
                result.passed_count,
                result.filtered_stale,
                result.filtered_placeholder,
                result.filtered_unsupported_sport,
                result.filtered_not_event,
                result.filtered_include,
                result.filtered_exclude,
            )

        return result.passed, result

    def _get_all_known_leagues(self) -> list[str]:
        """Get all known leagues from the league cache.

        Returns ALL leagues discovered from providers (ESPN, TSDB, etc.),
        not just the import-enabled leagues in the leagues table.
        This allows matching against any league for multi-sport groups.
        """
        with self._db_factory() as conn:
            cursor = conn.execute("SELECT league_slug FROM league_cache")
            return [row[0] for row in cursor.fetchall()]

    def _fetch_events(self, leagues: list[str], target_date: date) -> list[Event]:
        """Fetch events from data providers for leagues in parallel.

        Uses a fixed 7-day lookback (for weekly sports like NFL) and
        event_match_days_ahead setting for future events.
        """
        if not leagues:
            return []

        all_events: list[Event] = []
        num_workers = min(MAX_WORKERS, len(leagues))

        # Load date range settings
        # Note: days_back is hardcoded to 7 for weekly sports like NFL
        with self._db_factory() as conn:
            row = conn.execute(
                "SELECT event_match_days_ahead FROM settings WHERE id = 1"
            ).fetchone()
            days_back = 7  # Hardcoded for weekly sports
            days_ahead = (
                row["event_match_days_ahead"] if row and row["event_match_days_ahead"] else 3
            )

        # Build date range: [target - days_back, target + days_ahead]
        dates_to_fetch = [
            target_date + timedelta(days=offset) for offset in range(-days_back, days_ahead + 1)
        ]
        logger.debug(
            "[EVENT_EPG] Fetching events from %s to %s (%d days)",
            dates_to_fetch[0],
            dates_to_fetch[-1],
            len(dates_to_fetch),
        )

        def fetch_league_events(league: str, fetch_date: date) -> tuple[str, date, list[Event]]:
            """Fetch events for a single league/date (for parallel execution)."""
            try:
                # TSDB leagues: cache-only (don't hit API during EPG generation)
                # TSDB cache builds organically from startup/scheduled refresh
                is_tsdb = self._service.get_provider_name(league) == "tsdb"
                events = self._service.get_events(league, fetch_date, cache_only=is_tsdb)
                return (league, fetch_date, events)
            except Exception as e:
                logger.warning(
                    "[EVENT_EPG] Failed to fetch events for %s on %s: %s", league, fetch_date, e
                )
                return (league, fetch_date, [])

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            # Create tasks for all league/date combinations
            futures = {}
            for league in leagues:
                for fetch_date in dates_to_fetch:
                    future = executor.submit(fetch_league_events, league, fetch_date)
                    futures[future] = (league, fetch_date)

            for future in as_completed(futures):
                try:
                    league, fetch_date, events = future.result()
                    all_events.extend(events)
                except Exception as e:
                    league, fetch_date = futures[future]
                    logger.warning(
                        "[EVENT_EPG] Failed to fetch events for %s on %s: %s", league, fetch_date, e
                    )

        return all_events
