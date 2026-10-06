"""Diff a complete plan against one plugin's currently managed channels.

The diff only ever reads the plugin's own active rows: core channels and other
plugins' channels are structurally out of scope, so a plan cannot produce an
intention against them. Ambiguous adoption matches block the whole diff rather
than picking a winner — the host never mutates either candidate (Packet 8B
adoption contract).
"""

from __future__ import annotations

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
) -> PlanDiff:
    """Compare a complete plan with the plugin's channels, in plan order.

    Matching order per plan channel: exact logical key, then unambiguous
    adoption key, else create. Channels left unmatched are retire intentions.
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
            matched_channel_ids.add(existing.id)
            reasons = plan_field_reasons(conn, wanted, existing)
            if not reasons:
                continue
            kind: IntentionKind = (
                "stream_order" if reasons == ("ordered_stream_ids",) else "update"
            )
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
                        *plan_field_reasons(conn, wanted, existing),
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
) -> tuple[str, ...]:
    """Names of the host-visible fields where the plan differs from the row."""
    reasons: list[str] = []
    if wanted.display_name != existing.channel_name:
        reasons.append("display_name")
    if wanted.xmltv_channel_id != existing.tvg_id:
        reasons.append("xmltv_channel_id")
    if wanted.delete_at != load_host_time(existing.scheduled_delete_at):
        reasons.append("delete_at")
    current_streams = [s.dispatcharr_stream_id for s in get_channel_streams(conn, existing.id)]
    if list(wanted.ordered_stream_ids) != current_streams:
        reasons.append("ordered_stream_ids")
    return tuple(reasons)
