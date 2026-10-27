"""M3U stream fetching/filtering and known-league lookup for event groups."""

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from teamarr.database.groups import EventEPGGroup
from teamarr.services.stream_filter import FilterResult, StreamFilter, StreamFilterConfig

logger = logging.getLogger(__name__)


def stream_m3u_group(stream: Any, group_names: dict[int, str]) -> tuple[int | None, str | None]:
    """The stream's M3U group id and name, for exception keyword sources (#893).

    Dispatcharr's stream API returns the group id in ``channel_group``
    (``channel_group_id`` is unset); the name comes from the groups list.
    """
    group_id = getattr(stream, "channel_group_id", None)
    if group_id is None:
        group_id = getattr(stream, "channel_group", None)
    if not isinstance(group_id, int):
        return None, None
    return group_id, group_names.get(group_id)


def managed_channel_ids(db_factory: Any) -> set[int]:
    """Dispatcharr ids of Teamarr's own output channels.

    These are OUTPUT, never EPG-match input — callers pass them as
    ``exclude_channel_ids`` to the stream->channel map builders so they
    can't claim slots for streams shared with curated channels (#512).
    Module-level (not a mixin method) so both StreamFetcher and
    StreamMatching can use it without cross-mixin attribute access.
    """
    try:
        from teamarr.database.channels import get_all_managed_channels

        with db_factory() as conn:
            ids = {
                mc.dispatcharr_channel_id
                for mc in get_all_managed_channels(conn, include_deleted=False)
                if mc.dispatcharr_channel_id
            }
            if conn is None:
                has_team_channels = False
            else:
                has_team_channels = conn.execute(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'managed_team_channels'"
                ).fetchone()
                if has_team_channels:
                    ids.update(
                        row["dispatcharr_channel_id"]
                        for row in conn.execute(
                            "SELECT dispatcharr_channel_id FROM managed_team_channels "
                            "WHERE dispatcharr_channel_id IS NOT NULL"
                        )
                    )
            return ids
    except Exception as e:
        logger.warning("[CHANNEL_SOURCE] Failed to load managed channel ids: %s", e)
        return set()


@dataclass(frozen=True)
class DispatcharrCatalogInputs:
    """Read-only channel/guide snapshot shared by candidate fetching and resolution."""

    managed_ids: set[int]
    epg_data_list: list[dict]
    stream_channels: dict[int, dict]
    channel_by_uuid: dict[str, dict]


def dispatcharr_catalog_inputs(processor: Any) -> DispatcharrCatalogInputs:
    """Fetch the catalogs once per run; let callers handle failures without caching them.

    Exclude managed output channels before assigning stream slots (#512). New
    output channels created later in the run cannot enter this fixed snapshot.
    Stream details remain a per-group, eligible-id-only lookup (#647).
    """
    cached = getattr(processor, "_dispatcharr_catalog_cache", None)
    if cached is not None:
        return cached

    managed_ids = managed_channel_ids(processor._db_factory)
    channels = processor._dispatcharr_client.channels
    epg_data_list = channels.get_epg_data_list()
    stream_channels, channel_by_uuid = channels.get_channel_maps(exclude_channel_ids=managed_ids)
    inputs = DispatcharrCatalogInputs(
        managed_ids=managed_ids,
        epg_data_list=epg_data_list,
        stream_channels=stream_channels,
        channel_by_uuid=channel_by_uuid,
    )
    processor._dispatcharr_catalog_cache = inputs
    return inputs


class StreamFetcher:
    """Fetches and filters M3U streams from Dispatcharr for event groups.

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

    def _group_names(self, m3u_manager: Any) -> dict[int, str]:
        """M3U group id -> name, cached per processor instance (i.e. per run).

        ``_fetch_streams`` calls this once per event group, but the map
        itself is shared across the whole generation — caching it here means
        one ``list_groups()`` request per run instead of one per group.
        """
        cache = getattr(self, "_group_name_cache", None)
        if cache is None:
            try:
                cache = {g.id: g.name for g in m3u_manager.list_groups()}
            except Exception as e:
                logger.warning("[EVENT_EPG] Failed to list M3U groups: %s", e)
                cache = {}
            cache = cache or self._stored_group_names()
            self._group_name_cache = cache
        return cache

    def _stored_group_names(self) -> dict[int, str]:
        """Group names stored on attached streams, for when the groups list
        fails to load (it comes back empty). Without them every stream a
        keyword tagged by group name would read as untagged for the run.
        """
        from teamarr.database.channels import get_stored_m3u_group_names

        try:
            with self._db_factory() as conn:
                return get_stored_m3u_group_names(conn)
        except Exception as e:
            logger.warning("[EVENT_EPG] Failed to load stored M3U group names: %s", e)
            return {}

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
            return self._fetch_channel_source_streams(group)

        try:
            m3u_manager = self._dispatcharr_client.m3u

            # A source reads ONE M3U group. The old fallback here read every
            # stream in Dispatcharr when no group was bound; a pattern-only
            # source left unbound by #1056 did that four times a run on a real
            # install (123k streams each, 2M failed-match rows a day) (#1089).
            if not group.m3u_group_id:
                logger.warning(
                    "[EVENT_EPG] Source %r (id=%s) has no M3U group bound - nothing to read",
                    group.name,
                    group.id,
                )
                return []
            streams = m3u_manager.list_streams(group_id=group.m3u_group_id)

            # Convert to dicts for matcher (sorted by name for consistent order)
            account_names = self._account_names()
            group_names = self._group_names(m3u_manager)
            stream_dicts = []
            for s in streams:
                m3u_group_id, m3u_group_name = stream_m3u_group(s, group_names)
                stream_dicts.append(
                    {
                        "id": s.id,
                        "name": s.name,
                        "tvg_id": s.tvg_id,
                        "tvg_name": s.tvg_name,
                        # Loopback EPG resolution reads the source-channel uuid
                        # out of Dispatcharr-proxy URLs (see epg_resolver).
                        "url": s.url,
                        "channel_group": s.channel_group,
                        "channel_group_id": s.channel_group_id,
                        "m3u_group_id": m3u_group_id,
                        "m3u_group_name": m3u_group_name,
                        "m3u_account_id": s.m3u_account_id,
                        "m3u_account_name": account_names.get(s.m3u_account_id),
                        "is_stale": s.is_stale,
                    }
                )
            # Sort by stream ID ascending for consistent processing order
            stream_dicts.sort(key=lambda s: s["id"])
            return stream_dicts

        except Exception as e:
            logger.error("[EVENT_EPG] Failed to fetch streams: %s", e)
            return []

    def _fetch_channel_source_streams(self, group: EventEPGGroup | None = None) -> list[dict]:
        """Build EPG-match candidates from streams curated onto Dispatcharr channels.

        ``group`` is the channel-source row being processed. A row bound to one
        Dispatcharr channel group (#542) reads only that group's channels; the
        catch-all row (or no row) reads the groups selected in settings, or
        every group when none are selected.

        Epic 183.9. For each Dispatcharr channel that (a) carries an active,
        non-``_Teamarr`` EPG link and (b) is NOT one of Teamarr's own managed
        output channels, emit a candidate per assigned stream tagged with the
        CHANNEL's own EPG ``tvg_id`` — so the existing resolver/index path matches
        that channel's programs to events and attaches its streams. Teamarr's
        channels are OUTPUT, not INPUT, so they are excluded.
        """
        client = self._dispatcharr_client

        # Teamarr's own managed channels are OUTPUT — never treat them as a source.
        # Loaded BEFORE the channel-map fetch so they can be excluded from slot
        # claiming (#512): the map is last-write-wins, so once the attach window
        # opens a Teamarr event channel would steal a shared stream's slot from
        # the curated channel, dropping it from this pool and cascading into
        # delete/recreate churn on alternating runs.
        try:
            inputs = dispatcharr_catalog_inputs(self)
        except Exception as e:
            logger.warning("[CHANNEL_SOURCE] Failed to load channel/EPG data: %s", e)
            return []

        managed_ids = inputs.managed_ids
        stream_channel_map = inputs.stream_channels
        active_source_ids = self._active_epg_source_ids()
        epg_by_id = {e["id"]: e for e in inputs.epg_data_list if e.get("id") is not None}

        # M3U group ids already covered by an EPG-match-enabled group: streams in
        # those groups are matched by the per-group path (whose tier-1 resolution
        # uses the same channel EPG), so including them here would double-process
        # the identical match. Consolidation would dedupe the result anyway, but
        # skipping avoids wasted work and inflated source-group stats.
        epg_group_m3u_ids: set[int] = set()
        # User-selected DP channel groups to scope the scan (ybt.2). Empty = all.
        # Scoping skips the expensive EPG-resolution/matching for channels in
        # groups the user didn't pick — a generation-time saving.
        selected_groups: set[int] = set()
        try:
            from teamarr.database.groups import get_all_groups
            from teamarr.database.settings import get_epg_settings

            with self._db_factory() as conn:
                epg_group_m3u_ids = {
                    g.m3u_group_id
                    for g in get_all_groups(conn, include_disabled=False)
                    if g.epg_match_enabled and not g.is_channel_source and g.m3u_group_id
                }
                selected_groups = {
                    int(gid) for gid in get_epg_settings(conn).epg_channel_source_groups
                }
        except Exception as e:
            logger.warning("[CHANNEL_SOURCE] Failed to load group ids: %s", e)
        # A per-group row (#542) reads its own Dispatcharr group and nothing
        # else — set outside the try so a settings failure cannot widen it to
        # every group.
        row_group = getattr(group, "dispatcharr_channel_group_id", None)
        if row_group is not None:
            selected_groups = {int(row_group)}

        # DP channel group id -> name (#379). The channels API returns only
        # channel_group_id; the name (which dispatcharr_group ordering rules
        # match on, and which the rule-builder dropdown shows) lives in the
        # groups endpoint.
        dp_group_names = self._group_names(client.m3u)
        # The same endpoint names the streams' M3U groups (#893).
        m3u_group_names = dp_group_names

        # Pass 1: cheap eligibility from the channel map alone, so the stream
        # detail lookup below covers only the streams that can become
        # candidates — never the whole catalog (#647).
        eligible: list[tuple[int, dict, dict, int | None]] = []
        skipped_teamarr = 0
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
            eligible.append((stream_id, ch, ed, dp_group_id))

        # Stream detail (name, M3U group, account, staleness) for just those ids.
        detail_by_id: dict[int, Any] = {}
        if eligible:
            try:
                detail_by_id = {
                    s.id: s for s in client.m3u.get_streams_by_ids(sid for sid, *_ in eligible)
                }
            except Exception as e:
                logger.warning("[CHANNEL_SOURCE] Failed to fetch stream details: %s", e)

        candidates: list[dict] = []
        seen: set[int] = set()
        skipped_overlap = 0
        for stream_id, ch, ed, dp_group_id in eligible:
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
            m3u_group_id, m3u_group_name = stream_m3u_group(detail, m3u_group_names)
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
                    "m3u_group_id": m3u_group_id,
                    "m3u_group_name": m3u_group_name,
                    # The DP CHANNEL's own group (channel organization), distinct from
                    # the M3U stream group above — drives scoping + the sorting rule.
                    "dp_channel_group_id": dp_group_id,
                    "dp_channel_group": dp_group_names.get(dp_group_id)
                    if dp_group_id is not None
                    else None,
                    # The DP channel itself (#971) — drives the dispatcharr_channel rule
                    "dp_channel_id": ch.get("id"),
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
