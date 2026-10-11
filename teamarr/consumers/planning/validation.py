"""Host-state validation for an in-process plan (Packet 8C).

Record-level shape, size, and redaction rules live in ``contracts.py`` and run
the moment a ``PlanResult`` is constructed. This module adds the checks that
need host state: plugin scoping, programme windows against their channel,
XMLTV id collisions with channels the plan does not own, and stream/group/
profile hints against host-supplied catalogs. Validation never mutates
anything; a plan with diagnostics from here must not be applied.
"""

from __future__ import annotations

from collections.abc import Callable
from sqlite3 import Connection

from teamarr.consumers.planning.contracts import (
    ChannelPlan,
    PlanDiagnostic,
    PlanResult,
    ProgrammePlan,
)
from teamarr.database.channels.crud import get_active_tvg_id_owners, get_plugin_channels

# Each resolver receives the exact set of ids/names the plan mentions and
# returns the subset the host knows. Returning a subset lets one query answer
# "which of these are unknown?" without leaking catalog internals.
StreamIdResolver = Callable[[set[int]], set[int]]
HintResolver = Callable[[set[str]], set[str]]


def validate_plan(
    plan: PlanResult,
    *,
    expected_plugin_id: str,
    conn: Connection,
    resolve_stream_ids: StreamIdResolver | None = None,
    resolve_group_hints: HintResolver | None = None,
    resolve_profile_hints: HintResolver | None = None,
) -> list[PlanDiagnostic]:
    """Return every reason this plan must not mutate host channels.

    An empty list means the plan is valid against the supplied host state.
    Unknown-catalog checks are skipped when no resolver is given: Packet 8F
    wires the live Dispatcharr catalogs when planning enters the pipeline.
    """
    if plan.plugin_id != expected_plugin_id:
        return [
            PlanDiagnostic(
                code="plan.wrong_plugin",
                message=(
                    f"plan belongs to plugin {plan.plugin_id!r} "
                    f"but was submitted for {expected_plugin_id!r}"
                ),
            )
        ]

    diagnostics: list[PlanDiagnostic] = []
    diagnostics.extend(_programme_windows(plan.channels, plan.programmes))
    diagnostics.extend(_tvg_id_conflicts(conn, plan.plugin_id, plan.channels))
    if resolve_stream_ids is not None:
        diagnostics.extend(_unknown_streams(plan.channels, resolve_stream_ids))
    if resolve_group_hints is not None:
        diagnostics.extend(_unknown_hints(
            {c.group_hint for c in plan.channels if c.group_hint},
            resolve_group_hints,
            "plan.unknown_group_hint",
            "group hint is not a known channel group",
        ))
    if resolve_profile_hints is not None:
        mentioned = {hint for c in plan.channels for hint in c.profile_hints}
        diagnostics.extend(_unknown_hints(
            mentioned,
            resolve_profile_hints,
            "plan.unknown_profile_hint",
            "profile hint is not a known stream profile",
        ))
    diagnostics.sort(key=lambda d: (d.code, d.item_key or ""))
    return diagnostics


def _programme_windows(
    channels: list[ChannelPlan],
    programmes: list[ProgrammePlan],
) -> list[PlanDiagnostic]:
    windows = {c.logical_key: (c.programme_start_at, c.programme_end_at) for c in channels}
    diagnostics: list[PlanDiagnostic] = []
    for programme in programmes:
        start, end = windows.get(programme.channel_logical_key, (None, None))
        if start is None or end is None:
            # Dangling references are already rejected by PlanResult itself.
            continue
        if not (start <= programme.start and programme.stop <= end):
            diagnostics.append(
                PlanDiagnostic(
                    code="plan.programme_window",
                    message=(
                        f"programme {programme.programme_key} falls outside its "
                        "channel's programme window"
                    ),
                    item_key=programme.programme_key,
                )
            )
    return diagnostics


def _tvg_id_conflicts(
    conn: Connection,
    plugin_id: str,
    channels: list[ChannelPlan],
) -> list[PlanDiagnostic]:
    """Reject XMLTV ids already claimed by any channel the plan will not own.

    The plugin's own channels matched by logical key — or unambiguously by
    adoption key, since adoption renames that row in place — may keep or
    change their id freely; everything else (core channels, other plugins,
    even this plugin's *other* channels) is a conflict.
    """
    existing = get_plugin_channels(conn, plugin_id)
    plan_channels = channels
    matched_ids = {
        channel.id
        for channel in existing
        if channel.plugin_logical_key in {c.logical_key for c in plan_channels}
    }
    adoption_counts: dict[str, int] = {}
    for channel in existing:
        if channel.plugin_adoption_key:
            adoption_counts[channel.plugin_adoption_key] = (
                adoption_counts.get(channel.plugin_adoption_key, 0) + 1
            )
    for wanted in plan_channels:
        if adoption_counts.get(wanted.adoption_key) == 1:
            for channel in existing:
                if channel.plugin_adoption_key == wanted.adoption_key:
                    matched_ids.add(channel.id)
    owners = get_active_tvg_id_owners(
        conn,
        {c.xmltv_channel_id for c in plan_channels},
        exclude_channel_ids=matched_ids,
    )
    return [
        PlanDiagnostic(
            code="plan.tvg_id_conflict",
            message=(
                f"xmltv channel id {wanted.xmltv_channel_id} is already active "
                f"and owned by {owners[wanted.xmltv_channel_id]!r}"
            ),
            item_key=wanted.logical_key,
        )
        for wanted in channels
        if wanted.xmltv_channel_id in owners
    ]


def _unknown_streams(
    channels: list[ChannelPlan],
    resolve_stream_ids: StreamIdResolver,
) -> list[PlanDiagnostic]:
    wanted = {sid for c in channels for sid in c.ordered_stream_ids}
    known = resolve_stream_ids(wanted)
    return [
        PlanDiagnostic(
            code="plan.unknown_stream",
            message=(
                f"stream {sid} on channel {channel.logical_key} is not in the "
                "host stream catalog"
            ),
            item_key=channel.logical_key,
        )
        for channel in channels
        for sid in channel.ordered_stream_ids
        if sid not in known
    ]


def _unknown_hints(
    mentioned: set[str],
    resolver: HintResolver,
    code: str,
    message: str,
) -> list[PlanDiagnostic]:
    known = resolver(mentioned)
    return [
        PlanDiagnostic(code=code, message=f"{message}: {hint!r}", item_key=None)
        for hint in sorted(mentioned - known)
    ]
