"""Apply a validated plan diff through the existing lifecycle repositories.

Packet 8C application rules:

* Only a ``status="complete"`` plan that passes host validation and produces an
  unblocked diff may mutate anything. A failed plan never runs its deletion
  diff (the 8D failure-freeze preview).
* Every intention touches only the plugin's own rows. Repositories already
  scope plugin lookups by ``plugin_id``; ``update_managed_channel`` rejects
  ``plugin_*`` changes outright.
* Closed-loop writes: a Dispatcharr create/update/rename/delete must succeed
  before the local row claims success. A failed local insert after a remote
  create is compensated by deleting the just-created remote channel.
* ``dry_run=True`` (or the global ``DRY_RUN`` flag) returns the validated diff
  summary with zero writes.
* Per-intention failures are isolated and reported; the outcome carries
  everything the parent processing run should record under ``extra_metrics``.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from teamarr.config.runtime import dry_run as runtime_dry_run
from teamarr.consumers.planning.contracts import ChannelPlan, PlanDiagnostic, PlanResult
from teamarr.consumers.planning.diffing import PlanIntention, compute_plan_diff, plan_field_reasons
from teamarr.consumers.planning.validation import validate_plan
from teamarr.database.channel_numbers import get_next_channel_number
from teamarr.database.channels import (
    add_stream_to_channel,
    adopt_plugin_channel,
    create_managed_channel,
    get_channel_streams,
    log_channel_history,
    mark_channel_deleted,
    remove_stream_from_channel,
    update_managed_channel,
    update_stream_priority,
)

logger = logging.getLogger(__name__)


@dataclass
class PlanApplyOutcome:
    """What one plan application did (or, dry-run, would do)."""

    plugin_id: str
    plan_generation: int
    dry_run: bool
    created: list[str] = field(default_factory=list)
    adopted: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    stream_ordered: list[str] = field(default_factory=list)
    retired: list[str] = field(default_factory=list)
    failures: list[PlanDiagnostic] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def to_metrics(self) -> dict[str, Any]:
        """Shape for ``processing_runs.extra_metrics["plans"]`` (wired in 8F)."""
        return {
            "plugin_id": self.plugin_id,
            "plan_generation": self.plan_generation,
            "dry_run": self.dry_run,
            "created": len(self.created),
            "adopted": len(self.adopted),
            "updated": len(self.updated),
            "stream_ordered": len(self.stream_ordered),
            "retired": len(self.retired),
            "failures": [
                {"code": f.code, "message": f.message, "item_key": f.item_key}
                for f in self.failures
            ],
        }


class PlanApplier:
    """Turn one plugin's complete plan into host mutations, or a dry-run diff."""

    def __init__(
        self,
        db_factory: Callable[[], Any],
        *,
        channel_manager: Any | None = None,
    ) -> None:
        self._db_factory = db_factory
        self._channel_manager = channel_manager

    def apply(
        self,
        plan: PlanResult,
        *,
        plugin_id: str,
        plan_generation: int,
        dry_run: bool = False,
        resolve_stream_ids: Any | None = None,
        resolve_group_hints: Any | None = None,
        resolve_profile_hints: Any | None = None,
    ) -> PlanApplyOutcome:
        outcome = PlanApplyOutcome(
            plugin_id=plugin_id, plan_generation=plan_generation, dry_run=dry_run
        )
        if plan.status != "complete":
            outcome.failures.append(
                PlanDiagnostic(
                    code="plan.not_complete",
                    message=(
                        "only a complete plan may be applied; failed plans never "
                        "run the deletion diff"
                    ),
                )
            )
            return outcome

        with self._db_factory() as conn:
            diagnostics = validate_plan(
                plan,
                expected_plugin_id=plugin_id,
                conn=conn,
                resolve_stream_ids=resolve_stream_ids,
                resolve_group_hints=resolve_group_hints,
                resolve_profile_hints=resolve_profile_hints,
            )
            if diagnostics:
                outcome.failures.extend(diagnostics)
                return outcome

            diff = compute_plan_diff(conn, plan, plugin_id=plugin_id)
            if not diff.actionable:
                outcome.failures.extend(diff.blocked)
                return outcome

            if dry_run or runtime_dry_run():
                self._summarize(diff, outcome)
                return outcome

            for kind in ("create", "adopt", "update", "stream_order", "retire"):
                for intention in diff.intentions:
                    if intention.kind == kind:
                        self._execute(conn, intention, outcome)
        return outcome

    # -- intention dispatch -------------------------------------------------

    def _summarize(self, diff: Any, outcome: PlanApplyOutcome) -> None:
        for intention in diff.intentions:
            if intention.kind == "retire":
                existing = intention.existing
                key = (
                    existing.plugin_logical_key or str(existing.id) if existing is not None else "?"
                )
                outcome.retired.append(key)
                continue
            if intention.channel is None:
                continue
            if intention.kind == "create":
                outcome.created.append(intention.channel.logical_key)
            elif intention.kind == "adopt":
                outcome.adopted.append(intention.channel.logical_key)
            elif intention.kind == "update":
                outcome.updated.append(intention.channel.logical_key)
            elif intention.kind == "stream_order":
                outcome.stream_ordered.append(intention.channel.logical_key)

    def _execute(self, conn: Any, intention: PlanIntention, outcome: PlanApplyOutcome) -> None:
        channel, existing = intention.channel, intention.existing
        try:
            if intention.kind == "create":
                assert channel is not None
                self._create(conn, channel, outcome)
            elif intention.kind == "adopt":
                assert channel is not None and existing is not None
                self._adopt(conn, channel, existing, outcome)
            elif intention.kind == "update":
                assert channel is not None and existing is not None
                self._update(conn, channel, existing, intention.reasons, outcome)
            elif intention.kind == "stream_order":
                assert channel is not None and existing is not None
                self._sync_streams(conn, channel, existing, outcome)
            elif intention.kind == "retire":
                assert existing is not None
                self._retire(conn, existing, outcome)
        except Exception as exc:  # per-intention isolation
            self._rollback(conn)
            logger.error(
                "[PLAN] %s intention failed for plugin %s: %s",
                intention.kind,
                outcome.plugin_id,
                exc,
            )
            if channel is not None:
                key = channel.logical_key
            elif existing is not None:
                key = existing.plugin_logical_key or str(existing.id)
            else:
                key = "?"
            outcome.failures.append(
                PlanDiagnostic(code=f"plan.{intention.kind}_failed", message=str(exc), item_key=key)
            )

    @staticmethod
    def _rollback(conn: Any) -> None:
        try:
            conn.rollback()
        except Exception:
            logger.debug("[PLAN] rollback failed after intention failure", exc_info=True)

    # -- intention executors ------------------------------------------------

    def _create(self, conn: Any, wanted: ChannelPlan, outcome: PlanApplyOutcome) -> None:
        number = get_next_channel_number(conn)
        if number is None:
            outcome.failures.append(
                PlanDiagnostic(
                    code="plan.no_channel_number",
                    message="no free channel number in the global range",
                    item_key=wanted.logical_key,
                )
            )
            return
        if self._channel_manager is None:
            outcome.failures.append(
                PlanDiagnostic(
                    code="plan.dispatcharr_unavailable",
                    message="channel creation requires a Dispatcharr connection",
                    item_key=wanted.logical_key,
                )
            )
            return
        result = self._channel_manager.create_channel(
            name=wanted.display_name,
            channel_number=number,
            stream_ids=list(wanted.ordered_stream_ids),
            tvg_id=wanted.xmltv_channel_id,
        )
        if not result.success:
            outcome.failures.append(
                PlanDiagnostic(
                    code="plan.dispatcharr_create_failed",
                    message=result.error or "Dispatcharr channel creation failed",
                    item_key=wanted.logical_key,
                )
            )
            return
        remote = result.channel or {}
        remote_id = remote.get("id")
        try:
            channel_id = create_managed_channel(
                conn,
                None,
                wanted.event_key,
                "plugin",
                wanted.xmltv_channel_id,
                wanted.display_name,
                plugin_id=outcome.plugin_id,
                plugin_logical_key=wanted.logical_key,
                plugin_adoption_key=wanted.adoption_key,
                plugin_plan_generation=outcome.plan_generation,
                channel_number=number,
                dispatcharr_channel_id=remote_id,
                dispatcharr_uuid=remote.get("uuid"),
                scheduled_delete_at=wanted.delete_at.isoformat(),
                event_name=wanted.display_name,
            )
            for priority, stream_id in enumerate(wanted.ordered_stream_ids):
                add_stream_to_channel(conn, channel_id, stream_id, priority=priority)
            log_channel_history(
                conn,
                channel_id,
                "created",
                change_source="lifecycle",
                notes=f"plan generation {outcome.plan_generation}",
            )
            conn.commit()
        except Exception:
            self._rollback(conn)
            if remote_id is not None:
                # Compensate the remote create; the applier owns this because
                # the repository insert failed after the external mutation.
                self._channel_manager.delete_channel(remote_id)
            raise
        outcome.created.append(wanted.logical_key)

    def _adopt(
        self,
        conn: Any,
        wanted: ChannelPlan,
        existing: Any,
        outcome: PlanApplyOutcome,
    ) -> None:
        adopted = adopt_plugin_channel(
            conn,
            outcome.plugin_id,
            wanted.logical_key,
            wanted.adoption_key,
            wanted.display_name,
            wanted.xmltv_channel_id,
            rename_dispatcharr=self._rename_dispatcharr,
            plan_generation=outcome.plan_generation,
        )
        if adopted is None:
            outcome.failures.append(
                PlanDiagnostic(
                    code="plan.adoption_target_missing",
                    message="adoption key no longer matches an active channel",
                    item_key=wanted.logical_key,
                )
            )
            return
        # "modified": the history CHECK constraint has no "adopted" type; the
        # rename is recorded on the plugin_logical_key field with the plan
        # attribution in notes.
        log_channel_history(
            conn,
            adopted.id,
            "modified",
            change_source="lifecycle",
            field_name="plugin_logical_key",
            old_value=existing.plugin_logical_key,
            new_value=wanted.logical_key,
            notes=f"plugin plan adoption; plan generation {outcome.plan_generation}",
        )
        conn.commit()
        outcome.adopted.append(wanted.logical_key)
        reasons = plan_field_reasons(conn, wanted, adopted)
        if "delete_at" in reasons:
            update_managed_channel(
                conn, adopted.id, {"scheduled_delete_at": wanted.delete_at.isoformat()}
            )
            conn.commit()
        if "ordered_stream_ids" in reasons:
            self._sync_streams(conn, wanted, adopted, outcome)

    def _rename_dispatcharr(self, channel: Any, name: str, tvg_id: str) -> bool:
        if self._channel_manager is None or channel.dispatcharr_channel_id is None:
            return False
        result = self._channel_manager.update_channel(
            channel.dispatcharr_channel_id, {"name": name, "tvg_id": tvg_id}
        )
        return bool(result.success)

    def _update(
        self,
        conn: Any,
        wanted: ChannelPlan,
        existing: Any,
        reasons: tuple[str, ...],
        outcome: PlanApplyOutcome,
    ) -> None:
        db_updates: dict[str, Any] = {}
        remote_patch: dict[str, Any] = {}
        if "display_name" in reasons:
            db_updates["channel_name"] = wanted.display_name
            remote_patch["name"] = wanted.display_name
        if "xmltv_channel_id" in reasons:
            db_updates["tvg_id"] = wanted.xmltv_channel_id
            remote_patch["tvg_id"] = wanted.xmltv_channel_id
        if "delete_at" in reasons:
            db_updates["scheduled_delete_at"] = wanted.delete_at.isoformat()

        if remote_patch and existing.dispatcharr_channel_id is not None:
            if self._channel_manager is None:
                outcome.failures.append(
                    PlanDiagnostic(
                        code="plan.dispatcharr_unavailable",
                        message="channel update requires a Dispatcharr connection",
                        item_key=wanted.logical_key,
                    )
                )
                return
            result = self._channel_manager.update_channel(
                existing.dispatcharr_channel_id, remote_patch
            )
            if not result.success:
                # Closed loop: never record a local sync the remote rejected.
                outcome.failures.append(
                    PlanDiagnostic(
                        code="plan.dispatcharr_update_failed",
                        message=result.error or "Dispatcharr channel update failed",
                        item_key=wanted.logical_key,
                    )
                )
                return

        if db_updates:
            update_managed_channel(conn, existing.id, db_updates)
            log_channel_history(
                conn,
                existing.id,
                "modified",
                change_source="lifecycle",
                field_name=",".join(sorted(db_updates)),
                notes=f"plan generation {outcome.plan_generation}",
            )
            conn.commit()
        if "ordered_stream_ids" in reasons:
            self._sync_streams(conn, wanted, existing, outcome)
        outcome.updated.append(wanted.logical_key)

    def _sync_streams(
        self,
        conn: Any,
        wanted: ChannelPlan,
        existing: Any,
        outcome: PlanApplyOutcome,
    ) -> None:
        desired = list(wanted.ordered_stream_ids)
        current = get_channel_streams(conn, existing.id)
        by_stream_id = {row.dispatcharr_stream_id: row for row in current}
        for priority, stream_id in enumerate(desired):
            row = by_stream_id.get(stream_id)
            if row is None:
                add_stream_to_channel(conn, existing.id, stream_id, priority=priority)
            elif row.priority != priority:
                update_stream_priority(conn, row.id, priority)
        for row in current:
            if row.dispatcharr_stream_id not in desired:
                remove_stream_from_channel(
                    conn, existing.id, row.dispatcharr_stream_id, reason="plugin_plan"
                )
        conn.commit()

        if existing.dispatcharr_channel_id is None or self._channel_manager is None:
            return
        result = self._channel_manager.update_channel(
            existing.dispatcharr_channel_id, {"streams": desired}
        )
        if not result.success:
            # Local priorities remain the desired state and drift detection
            # retries the push (as with core ordering), but a plan apply still
            # reports the gap so the run surfaces it.
            outcome.failures.append(
                PlanDiagnostic(
                    code="plan.stream_push_failed",
                    message=result.error or "Dispatcharr stream order push failed",
                    item_key=wanted.logical_key,
                )
            )
        else:
            outcome.stream_ordered.append(wanted.logical_key)

    def _retire(self, conn: Any, existing: Any, outcome: PlanApplyOutcome) -> None:
        if existing.dispatcharr_channel_id is not None:
            if self._channel_manager is None:
                outcome.failures.append(
                    PlanDiagnostic(
                        code="plan.dispatcharr_unavailable",
                        message="retiring requires a Dispatcharr connection",
                        item_key=existing.plugin_logical_key,
                    )
                )
                return
            result = self._channel_manager.delete_channel(existing.dispatcharr_channel_id)
            if not result.success:
                # Keep the row so the retire is retried on the next plan; do
                # not orphan the remote channel by deleting the row locally.
                outcome.failures.append(
                    PlanDiagnostic(
                        code="plan.dispatcharr_delete_failed",
                        message=result.error or "Dispatcharr channel delete failed",
                        item_key=existing.plugin_logical_key,
                    )
                )
                return
        mark_channel_deleted(conn, existing.id, reason="plugin_plan_retire")
        log_channel_history(
            conn,
            existing.id,
            "deleted",
            change_source="lifecycle",
            notes=f"plan generation {outcome.plan_generation}",
        )
        conn.commit()
        outcome.retired.append(existing.plugin_logical_key or str(existing.id))


__all__ = ["PlanApplier", "PlanApplyOutcome"]
