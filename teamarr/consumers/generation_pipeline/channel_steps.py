"""Stream ordering and diagnostic-audit implementation for generation."""

from __future__ import annotations

import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from teamarr.dispatcharr.factory import DispatcharrConnection
from teamarr.services import TeamChannelManager

if TYPE_CHECKING:  # pragma: no cover - typing only
    from teamarr.consumers.generation_pipeline.models import GenerationContext

# Retain generation's established logger name for compatibility with log-based
# diagnostics and tests while this implementation lives in a separate module.
logger = logging.getLogger("teamarr.consumers.generation")

_ORDERING_PUSH_WORKERS = 8


def stage_stream_ordering(
    context: GenerationContext,
    apply_ordering: Callable[[Callable[[], Any], Any, Callable, bool], dict],
) -> None:
    """Apply stream-ordering rules after channel numbering."""
    context.report("ordering", 93, "Applying stream ordering rules...")
    context.result.stream_ordering = apply_ordering(
        context.db_factory, context.dispatcharr_client, context.report, context.manual
    )


@dataclass
class _OrderingPlan:
    """One channel's decided stream-ordering state, ready for the push phase.

    Carries everything the push decision needs so phase 2 can run without going
    back to the database and phase 3 can run without touching it at all (#735).
    """

    channel: Any
    current_order: list[int] | None  # what Dispatcharr is holding (#712)
    pinned_top: int | None  # live-event #1 pin (#232)
    reordered_count: int
    has_windowed: bool


def _push_stream_orders(
    channel_mgr: Any,
    pushes: list[tuple[_OrderingPlan, list[int]]],
    update_progress: Callable,
) -> int:
    """PATCH each channel's stream order to Dispatcharr, concurrently (#735).

    One PATCH per channel used to go out serially, and since #712 any order
    difference triggers one — so a windowed install re-pushes most of its
    channels every run and this was the longest serial stretch left. The work
    is pure network wait: ``update_channel`` guards only a cache write, and the
    client pools its connections.

    Failures are logged and counted, never raised: Dispatcharr still holds the
    wrong order, so the drift check re-detects it and retries next run. Nothing
    is rolled back for the same reason (see #712).

    Returns:
        The number of channels whose push failed.
    """
    workers = min(_ORDERING_PUSH_WORKERS, len(pushes))
    failures = 0
    done = 0
    total = len(pushes)

    def push(plan: _OrderingPlan, ordered_ids: list[int]):
        return plan, channel_mgr.update_channel(
            plan.channel.dispatcharr_channel_id, {"streams": ordered_ids}
        )

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="order-push") as executor:
        futures = [executor.submit(push, plan, ids) for plan, ids in pushes]
        for future in as_completed(futures):
            done += 1
            try:
                plan, sync_result = future.result()
            except Exception as e:  # noqa: BLE001 — per-channel isolation
                failures += 1
                logger.warning("[ORDERING] Stream-order push raised: %s", e)
            else:
                if not sync_result.success:
                    failures += 1
                    logger.warning(
                        "[ORDERING] Failed to sync channel %s to Dispatcharr: %s",
                        plan.channel.channel_name,
                        sync_result.error,
                    )
            if done % 10 == 0 or done == total:
                pct = 93 + int((done / total) * 2)
                update_progress(
                    "ordering", pct, f"Ordering streams ({done}/{total})", done, total, ""
                )

    logger.info(
        "[ORDERING] Pushed stream order for %d channel(s) across %d worker(s); %d failed",
        total,
        workers,
        failures,
    )
    return failures


def apply_stream_ordering(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
    update_progress: Callable,
    manual: bool = False,
    *,
    channel_manager_factory: Callable[[Any], Any],
) -> dict:
    """Apply stream ordering rules to all managed channels.

    ``manual`` (#232): a user-triggered run bypasses the live-event #1 pin —
    the escape hatch when the pinned stream is wrong. Scheduled runs keep the
    top slot of an in-window event's channel stable so a re-gen can't displace
    the stream a viewer is currently watching; rule-truth priorities are still
    persisted, so normal ordering resumes on the first post-event push. That
    post-event push is guaranteed since #712: once the pin lifts, the intended
    order no longer matches what Dispatcharr holds, and order drift alone is
    enough to trigger a push.
    """
    from teamarr.consumers.lifecycle import is_channel_event_live
    from teamarr.database.channels import (
        get_all_channel_streams,
        get_all_managed_channels,
        get_all_ordered_stream_ids,
        update_stream_priority,
    )
    from teamarr.database.channels.streams import (
        get_active_dispatcharr_stream_ids,
        refresh_stream_stats_bulk,
    )
    from teamarr.database.settings import get_stream_ordering_settings
    from teamarr.database.stream_ordering_scopes import get_stream_ordering_scopes
    from teamarr.services.stream_ordering import get_stream_ordering_service
    from teamarr.utilities.tz import now_utc

    reorder_result: dict = {
        "channels_reordered": 0,
        "streams_reordered": 0,
        "windows_synced": 0,
        "order_drift_synced": 0,
        "stats_refreshed": 0,
    }
    try:
        with db_factory() as conn:
            ordering_settings = get_stream_ordering_settings(conn)
            # No early return when rules are absent: time-windowed (EPG-matched)
            # streams still need their membership synced each run so they attach
            # when their window opens and detach when it closes (bead teamarr-uye).
            scoped_ordering = get_stream_ordering_scopes(conn)
            has_scoped_rules = any(scope.rules for scope in scoped_ordering)
            if ordering_settings.rules or has_scoped_rules:
                logger.info("[ORDERING] Applying scoped stream ordering rules")
            else:
                logger.debug("[ORDERING] No ordering rules configured; running window sync only")

            # Setup Dispatcharr channel manager once if available
            channel_mgr = None
            if dispatcharr_client:
                raw_client = (
                    dispatcharr_client.client
                    if isinstance(dispatcharr_client, DispatcharrConnection)
                    else dispatcharr_client
                )
                channel_mgr = channel_manager_factory(raw_client)

            # Dispatcharr's ACTUAL stream order per channel (#712). Until now the
            # push below was gated purely on whether a local priority CHANGED, and
            # priorities are already computed at insert time
            # (creator.py::compute_stream_priority_from_rules) — so a steady-state
            # channel recomputes to the value it already has, reordered_count is 0,
            # and Teamarr never pushed no matter what order Dispatcharr was holding.
            # Any divergence (a rejected push, a hand edit in Dispatcharr, a
            # reconciliation fix that wrote the wrong order) was therefore permanent.
            # One list call on a fresh manager cache — the audit at the end of the
            # run pays the same cost — gives us the real order to converge against.
            dispatcharr_order: dict[int, list[int]] = {}
            if channel_mgr:
                try:
                    for d_channel in channel_mgr.get_channels():
                        dispatcharr_order[d_channel.id] = list(d_channel.streams or ())
                except Exception as e:
                    # Order convergence is best-effort: without it we fall back to
                    # the old change-gated behavior rather than failing the run.
                    logger.warning("[ORDERING] Could not read Dispatcharr stream order: %s", e)

            all_channels = get_all_managed_channels(conn, include_deleted=False)

            # One scan each instead of two queries per channel (#735). The
            # window instant is pinned for the whole pass so every channel's
            # attach/detach state is evaluated at the same moment — walking
            # channels one at a time re-read the clock per channel, so a long
            # pass could open a window partway through and treat two channels
            # sharing a stream inconsistently.
            window_now = now_utc().strftime("%Y-%m-%d %H:%M:%S")
            streams_by_channel = get_all_channel_streams(conn)
            pre_order_by_channel = get_all_ordered_stream_ids(conn, now=window_now)

            # stats_metric rules score against the cached stream_stats column,
            # and until now that column was only ever refreshed by the streams
            # page — one endpoint, driven by a human opening a channel (#576,
            # #616). Every scheduled run therefore ordered on whatever numbers
            # happened to be cached, which on a real install means months old or
            # absent entirely. Pull them once, in bulk, before any priority is
            # computed.
            #
            # Skipped outright when no rule reads stats: the fetch buys nothing
            # for a ruleset built from m3u/group/regex, and most are.
            has_stats_rule = any(
                rule.type == "stats_metric" for rule in ordering_settings.rules
            ) or any(
                rule.get("type") == "stats_metric"
                for scope in scoped_ordering
                for rule in scope.rules
            )
            if has_stats_rule:
                stat_stream_ids = get_active_dispatcharr_stream_ids(conn)
                refreshed = refresh_stream_stats_bulk(conn, stat_stream_ids)
                reorder_result["stats_refreshed"] = refreshed
                logger.info(
                    "[ORDERING] Refreshed stats for %d/%d stream(s) before scoring",
                    refreshed,
                    len(stat_stream_ids),
                )

            # Phase 1 (serial, database): recompute and persist priorities.
            # Nothing here touches the network, so it stays on the one
            # connection; the pushes are batched up and issued afterwards.
            plans: list[_OrderingPlan] = []

            for channel in all_channels:
                streams = streams_by_channel.get(channel.id)
                if not streams:
                    continue

                current_order = (
                    dispatcharr_order.get(channel.dispatcharr_channel_id)
                    if channel.dispatcharr_channel_id
                    else None
                )

                # Live-event #1 pin (#232): capture the currently-pushed top
                # stream BEFORE priorities are recomputed, so the push below
                # can keep it in the top slot mid-broadcast.
                #
                # Read it from Dispatcharr's real order when we have it (#712):
                # the pin's premise is that slot 1 is what somebody is watching,
                # and that is Dispatcharr's slot 1, not ours. Falling back to the
                # DB order would pin the wrong stream on exactly the channels
                # whose order has drifted — and now that drift alone triggers a
                # push, that would displace the live stream instead of leaving it
                # alone.
                pinned_top: int | None = None
                if not manual and is_channel_event_live(
                    channel.event_date, channel.scheduled_delete_at
                ):
                    pre_order = (
                        current_order
                        if current_order is not None
                        else pre_order_by_channel.get(channel.id, [])
                    )
                    pinned_top = pre_order[0] if pre_order else None
                    # The pin's premise is that slot 1 is what somebody is
                    # watching. A probe saying the stream is dead or a black
                    # screen contradicts that premise, and the pin has to yield
                    # to it (#670): an in-flight session has already failed over
                    # to slot 2, while every new tune-in pays the failover
                    # again. Holding it would also silently undo the demotion a
                    # stats_metric rule just made — the priority lands in the DB
                    # and never reaches Dispatcharr — for the whole live window.
                    #
                    # Only a measurement lifts the pin. No stats, absent keys
                    # and unreadable stats all leave it in place, because those
                    # say nothing about the stream and holding when nothing is
                    # known is exactly what the pin is for.
                    if pinned_top is not None:
                        top = next(
                            (s for s in streams if s.dispatcharr_stream_id == pinned_top), None
                        )
                        if top is not None and top.measured_dead_or_blank:
                            logger.info(
                                "[STREAM_AUDIT] pin: ch='%s' (d_id=%s) live event — "
                                "released stream %d from #1, measured dead/blank (#670)",
                                channel.channel_name,
                                channel.dispatcharr_channel_id,
                                pinned_top,
                            )
                            pinned_top = None

                reordered_count = 0
                ordering_service = get_stream_ordering_service(conn, channel.sport, channel.league)
                if ordering_service.rules:
                    for stream in streams:
                        new_priority = ordering_service.compute_priority(stream)
                        if stream.priority != new_priority:
                            update_stream_priority(conn, stream.id, new_priority)
                            reordered_count += 1

                if reordered_count > 0:
                    reorder_result["channels_reordered"] += 1
                    reorder_result["streams_reordered"] += reordered_count

                if channel_mgr and channel.dispatcharr_channel_id:
                    plans.append(
                        _OrderingPlan(
                            channel=channel,
                            current_order=current_order,
                            pinned_top=pinned_top,
                            reordered_count=reordered_count,
                            # A channel with any time-windowed stream must be
                            # synced every run: membership flips as the window
                            # opens and closes.
                            has_windowed=any(s.attach_at for s in streams),
                        )
                    )

            # Phase 2 (serial, database): one scan for the post-update active
            # sets, then decide what actually needs pushing.
            post_order_by_channel = get_all_ordered_stream_ids(conn, now=window_now)
            pushes: list[tuple[_OrderingPlan, list[int]]] = []

            for plan in plans:
                channel = plan.channel
                # An empty set IS pushed — a channel whose sole source is
                # currently out-of-window must be cleared (it re-attaches on a
                # later run).
                ordered_ids = list(post_order_by_channel.get(channel.id, []))

                if (
                    plan.pinned_top is not None
                    and ordered_ids
                    and ordered_ids[0] != plan.pinned_top
                    and plan.pinned_top in ordered_ids
                ):
                    # Event is live: rule-truth priorities are in the DB, but
                    # the push keeps the current #1 on top so the stream being
                    # watched isn't displaced mid-broadcast.
                    ordered_ids.remove(plan.pinned_top)
                    ordered_ids.insert(0, plan.pinned_top)
                    logger.info(
                        "[STREAM_AUDIT] pin: ch='%s' (d_id=%s) live event — "
                        "kept stream %d at #1 (#232)",
                        channel.channel_name,
                        channel.dispatcharr_channel_id,
                        plan.pinned_top,
                    )

                # Compared AFTER the pin is applied, so a pinned channel is
                # measured against the order we actually intend to push and
                # doesn't re-push every run.
                order_drifted = plan.current_order is not None and ordered_ids != plan.current_order

                if not (plan.reordered_count > 0 or plan.has_windowed or order_drifted):
                    continue

                if plan.has_windowed:
                    reorder_result["windows_synced"] += 1
                if order_drifted and plan.reordered_count == 0 and not plan.has_windowed:
                    reorder_result["order_drift_synced"] += 1
                    logger.info(
                        "[STREAM_AUDIT] drift: ch='%s' (d_id=%s) Dispatcharr order "
                        "%s does not match intended %s — re-pushing (#712)",
                        channel.channel_name,
                        channel.dispatcharr_channel_id,
                        plan.current_order,
                        ordered_ids,
                    )
                logger.info(
                    "[STREAM_AUDIT] sync: ch='%s' (d_id=%s) setting streams=%s "
                    "count=%d (reordered=%d windowed=%s drifted=%s)",
                    channel.channel_name,
                    channel.dispatcharr_channel_id,
                    ordered_ids,
                    len(ordered_ids),
                    plan.reordered_count,
                    plan.has_windowed,
                    order_drifted,
                )
                pushes.append((plan, ordered_ids))

        # Team channels are durable and use their own membership table, but
        # their streams obey the same scoped ordering rules and windows. This
        # opens its own connection and issues its own PATCHes, so it runs only
        # once the block above has committed and closed (#735, #826).
        team_ordering = TeamChannelManager(db_factory, channel_mgr).sync_stream_ordering()
        reorder_result["managed_team_channels_reordered"] = team_ordering["channels"]
        reorder_result["managed_team_streams_reordered"] = team_ordering["streams"]
        if team_ordering["errors"]:
            reorder_result["managed_team_order_errors"] = team_ordering["errors"]

        # Phase 3 (parallel, network only): issue the pushes. Outside the `with`
        # so the database connection is closed before any thread runs — every
        # decision is already made and nothing below writes to it.
        #
        # This was the longest serial stretch left in a run: one PATCH per
        # channel, and since #712 any order difference triggers one, so a
        # windowed install pushes most of its channels every run. update_channel
        # is thread-safe (its only shared state is a locked cache write) and the
        # client pools connections, so the wait is pure overlap.
        if pushes:
            failed = _push_stream_orders(channel_mgr, pushes, update_progress)
            reorder_result["push_failures"] = failed

        if (
            reorder_result["channels_reordered"] > 0
            or reorder_result["windows_synced"] > 0
            or reorder_result["order_drift_synced"] > 0
        ):
            logger.info(
                "[ORDERING] Reordered %d streams across %d channels; "
                "window-synced %d channel(s); order-drift re-pushed %d channel(s)",
                reorder_result["streams_reordered"],
                reorder_result["channels_reordered"],
                reorder_result["windows_synced"],
                reorder_result["order_drift_synced"],
            )
    except Exception as e:
        logger.warning("[ORDERING] Stream ordering failed: %s", e)
        reorder_result["error"] = str(e)

    return reorder_result


def run_stream_audit(
    db_factory: Callable[[], Any],
    dispatcharr_client: Any | None,
    *,
    channel_manager_factory: Callable[[Any], Any],
) -> None:
    """Post-generation audit: compare DB stream counts vs Dispatcharr.

    Logs any channels where the DB and Dispatcharr disagree on stream
    assignments. This is diagnostic-only — no changes are made.
    """
    from teamarr.consumers.lifecycle import is_channel_event_live
    from teamarr.database.channels import get_all_managed_channels, get_all_ordered_stream_ids

    if not dispatcharr_client:
        return

    channel_attr = getattr(dispatcharr_client, "channels", None)
    raw_client = channel_attr._client if channel_attr else None
    if not raw_client:
        return

    channel_mgr = channel_manager_factory(raw_client)
    mismatches = []
    order_mismatches = []

    with db_factory() as conn:
        channels = get_all_managed_channels(conn, include_deleted=False)
        # One scan for every channel's active set instead of a query each (#735).
        ordered_by_channel = get_all_ordered_stream_ids(conn)

        for channel in channels:
            if not channel.dispatcharr_channel_id:
                continue

            # Window-gated active set (same set we actually push to Dispatcharr).
            # Using the raw stream list here would false-flag time-shared EPG
            # streams that are correctly out of their attach/detach window (183.5)
            # as mismatches. Mirrors reconciliation's expected-set logic.
            #
            # Kept in priority order (#712): this audit used to sort both sides
            # before comparing, so it could only ever see membership — it logged
            # "All channels match" on runs where Dispatcharr held a visibly
            # different order. Order is the whole point of the ordering step, so
            # the audit has to be able to see it.
            db_stream_ids = ordered_by_channel.get(channel.id, [])

            d_channel = channel_mgr.get_channel(channel.dispatcharr_channel_id)
            if not d_channel:
                logger.warning(
                    "[STREAM_AUDIT] MISSING: ch='%s' (d_id=%s) exists in DB "
                    "but not in Dispatcharr (db_streams=%s)",
                    channel.channel_name,
                    channel.dispatcharr_channel_id,
                    db_stream_ids,
                )
                continue

            d_stream_ids = list(d_channel.streams or ())

            if sorted(db_stream_ids) != sorted(d_stream_ids):
                mismatches.append(channel.channel_name)
                logger.warning(
                    "[STREAM_AUDIT] MISMATCH: ch='%s' (d_id=%s) "
                    "db_streams=%s (%d) vs dispatcharr_streams=%s (%d)",
                    channel.channel_name,
                    channel.dispatcharr_channel_id,
                    sorted(db_stream_ids),
                    len(db_stream_ids),
                    sorted(d_stream_ids),
                    len(d_stream_ids),
                )
            elif db_stream_ids != d_stream_ids:
                # Same streams, different order. Expected on a live channel: the
                # #1 pin (#232) deliberately holds the watched stream on top,
                # against the DB's rule-truth order, until the event ends.
                if is_channel_event_live(channel.event_date, channel.scheduled_delete_at):
                    logger.debug(
                        "[STREAM_AUDIT] pinned order: ch='%s' (d_id=%s) "
                        "db_order=%s vs dispatcharr_order=%s (live event, #232)",
                        channel.channel_name,
                        channel.dispatcharr_channel_id,
                        db_stream_ids,
                        d_stream_ids,
                    )
                else:
                    order_mismatches.append(channel.channel_name)
                    logger.warning(
                        "[STREAM_AUDIT] ORDER MISMATCH: ch='%s' (d_id=%s) same %d "
                        "stream(s), different order: db_order=%s vs dispatcharr_order=%s",
                        channel.channel_name,
                        channel.dispatcharr_channel_id,
                        len(db_stream_ids),
                        db_stream_ids,
                        d_stream_ids,
                    )

    if mismatches:
        logger.warning(
            "[STREAM_AUDIT] %d channel(s) have stream mismatches: %s",
            len(mismatches),
            mismatches[:20],  # Cap at 20 to avoid log spam
        )
    if order_mismatches:
        logger.warning(
            "[STREAM_AUDIT] %d channel(s) have stream ORDER mismatches: %s",
            len(order_mismatches),
            order_mismatches[:20],
        )
    if not mismatches and not order_mismatches:
        logger.info("[STREAM_AUDIT] All channels match between DB and Dispatcharr")
