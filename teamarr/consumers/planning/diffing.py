"""Diff a complete plan against one plugin's currently managed channels.

The diff only ever reads the plugin's own active rows: core channels and other
plugins' channels are structurally out of scope, so a plan cannot produce an
intention against them. Ambiguous adoption matches block the whole diff rather
than picking a winner — the host never mutates either candidate (Packet 8B
adoption contract).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from sqlite3 import Connection
from typing import Literal

from teamarr.consumers.planning.contracts import ChannelPlan, PlanDiagnostic, PlanResult
from teamarr.database.channels.crud import get_plugin_channels
from teamarr.database.channels.streams import get_channel_streams
from teamarr.database.channels.types import ManagedChannel

IntentionKind = Literal["create", "adopt", "update", "stream_order", "retire"]


def load_host_time(value: datetime | str | None) -> datetime | None:
    """Parse a stored lifecycle timestamp; naive values are read as UTC.

    ``managed_channels`` timestamp columns hold ``isoformat()`` strings and the
    connection registers no sqlite converters, so ``ManagedChannel`` fields can
    be strings at runtime even where annotated as ``datetime``.
    """
    if value is None or isinstance(value, datetime):
        return value
    parsed = datetime.fromisoformat(value)
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


@dataclass(frozen=True)
class PlanIntention:
    """One actionable delta between the plan and host state."""

    kind: IntentionKind
    channel: ChannelPlan | None = None  # absent only for retire
    existing: ManagedChannel | None = None  # absent only for create
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanDiff:
    plugin_id: str
    intentions: tuple[PlanIntention, ...] = ()
    blocked: tuple[PlanDiagnostic, ...] = ()

    @property
    def actionable(self) -> bool:
        """False when adoption ambiguity (or another blocker) forbids mutation."""
        return not self.blocked


def compute_plan_diff(
    conn: Connection,
    plan: PlanResult,
    *,
    plugin_id: str,
    remote_stream_orders: Mapping[int, Sequence[int]] | None = None,
) -> PlanDiff:
    """Compare a complete plan with the plugin's channels, in plan order.

    Matching order per plan channel: exact logical key, then unambiguous
    adoption key, else create. Channels left unmatched are retire intentions.

    ``remote_stream_orders`` (Dispatcharr channel id → its real stream array)
    lets the diff see remote drift the local rows cannot (#712): array order
    IS priority in Dispatcharr, and a channel can be reordered by hand there
    while Teamarr's rows still match the plan.
    """
    if plan.plugin_id != plugin_id:
        return PlanDiff(
            plugin_id=plugin_id,
            blocked=(
                PlanDiagnostic(
                    code="plan.wrong_plugin",
                    message=f"plan belongs to plugin {plan.plugin_id!r}, not {plugin_id!r}",
                ),
            ),
        )

    existing_channels = get_plugin_channels(conn, plugin_id)
    by_logical = {c.plugin_logical_key: c for c in existing_channels if c.plugin_logical_key}
    adoption_candidates: dict[str, list[ManagedChannel]] = {}
    for channel in existing_channels:
        if channel.plugin_adoption_key:
            adoption_candidates.setdefault(channel.plugin_adoption_key, []).append(channel)

    intentions: list[PlanIntention] = []
    blocked: list[PlanDiagnostic] = []
    matched_channel_ids: set[int] = set()

    for wanted in plan.channels:
        existing = by_logical.get(wanted.logical_key)
        if existing is not None:
            if existing.id in matched_channel_ids:
                # An earlier plan item already claimed this row (via adoption);
                # a second item resolving onto it would double-own the channel.
                blocked.append(
                    PlanDiagnostic(
                        code="plan.logical_key_conflict",
                        message=(
                            f"logical key {wanted.logical_key!r} resolves to a "
                            "channel another plan item already matched; "
                            "refusing to give one row two owners"
                        ),
                        item_key=wanted.logical_key,
                    )
                )
                continue
            matched_channel_ids.add(existing.id)
            reasons = plan_field_reasons(
                conn, wanted, existing, remote_stream_orders=remote_stream_orders
            )
            if not reasons:
                continue
            kind: IntentionKind = "stream_order" if reasons == ("ordered_stream_ids",) else "update"
            intentions.append(
                PlanIntention(kind=kind, channel=wanted, existing=existing, reasons=reasons)
            )
            continue

        candidates = [
            channel
            for channel in adoption_candidates.get(wanted.adoption_key, [])
            if channel.id not in matched_channel_ids
        ]
        if len(candidates) > 1:
            blocked.append(
                PlanDiagnostic(
                    code="plan.ambiguous_adoption",
                    message=(
                        f"adoption key {wanted.adoption_key!r} matches "
                        f"{len(candidates)} active channels; refusing to choose"
                    ),
                    item_key=wanted.logical_key,
                )
            )
        elif len(candidates) == 1:
            existing = candidates[0]
            matched_channel_ids.add(existing.id)
            intentions.append(
                PlanIntention(
                    kind="adopt",
                    channel=wanted,
                    existing=existing,
                    reasons=(
                        "adopted_by_adoption_key",
                        *plan_field_reasons(
                            conn, wanted, existing, remote_stream_orders=remote_stream_orders
                        ),
                    ),
                )
            )
        else:
            intentions.append(PlanIntention(kind="create", channel=wanted))

    intentions.extend(
        PlanIntention(kind="retire", existing=channel, reasons=("absent_from_complete_plan",))
        for channel in existing_channels
        if channel.id not in matched_channel_ids
    )
    if blocked:
        # An ambiguous adoption blocks the entire diff: no intentions at all,
        # so nothing downstream can act on a partial interpretation.
        return PlanDiff(plugin_id=plugin_id, blocked=tuple(blocked))
    return PlanDiff(plugin_id=plugin_id, intentions=tuple(intentions), blocked=tuple(blocked))


def plan_field_reasons(
    conn: Connection,
    wanted: ChannelPlan,
    existing: ManagedChannel,
    remote_stream_orders: Mapping[int, Sequence[int]] | None = None,
) -> tuple[str, ...]:
    """Names of the host-visible fields where the plan differs from the row.

    Stream order fires on a difference against the local rows OR — when a
    snapshot of Dispatcharr's real stream arrays is supplied — against that
    snapshot: array order IS priority there (#712), and the remote channel can
    drift while the local rows still match the plan. A channel missing from
    the snapshot is unknown, not empty; no reason fires for it.
    """
    reasons: list[str] = []
    if wanted.display_name != existing.channel_name:
        reasons.append("display_name")
    if wanted.xmltv_channel_id != existing.tvg_id:
        reasons.append("xmltv_channel_id")
    if wanted.delete_at != load_host_time(existing.scheduled_delete_at):
        reasons.append("delete_at")
    desired = list(wanted.ordered_stream_ids)
    current_streams = [s.dispatcharr_stream_id for s in get_channel_streams(conn, existing.id)]
    external = getattr(existing, "ordering_owner", "teamarr") == "podium"
    membership_changed = set(desired) != set(current_streams)
    if membership_changed or (not external and desired != current_streams):
        reasons.append("ordered_stream_ids")
    elif (
        not external
        and remote_stream_orders is not None
        and existing.dispatcharr_channel_id is not None
    ):
        remote = remote_stream_orders.get(existing.dispatcharr_channel_id)
        if remote is not None and desired != list(remote):
            reasons.append("ordered_stream_ids")
    return tuple(reasons)
