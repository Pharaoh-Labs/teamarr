# In-process plan contract v1 (Packets 8A–8C)

This is a **shadow-mode proof**, not a plugin runtime or an applied channel
plan. The models live in `teamarr/consumers/planning/contracts.py`; a caller
can snapshot the existing event-group matcher output (`stream` + `event`) and
its already-generated `Programme` records with `snapshot_event_group_match()`,
then pass that `PlanRequest` to `EventGroupShadowSource.plan()`. Normal
generation does not invoke this source. It has no database or Dispatcharr
connection and does not publish XMLTV.

All records reject unknown fields. `PlanRequest` and `PlanResult` have
`schema_version: 1`; unknown versions are rejected. Snapshots include only
numeric stream IDs and source keys, not raw stream URLs, M3U account names,
or credentials. Optional flat metadata rejects sensitive key names and URL
values. Times require offsets and are normalized to UTC. A plan is limited to
500 channels, 5,000 programmes, 500 diagnostics, and 1 MiB of serialized JSON;
`decode_plan_request()` and `decode_plan_result()` check input size **before**
parsing; their encoders check the serialized output as well.

`status="complete"` with empty channel/programme lists means an explicitly
complete empty plan. `status="failed"` requires a diagnostic and forbids
actionable records. Missing programme/stream data in the shadow adapter yields
`failed`, never an empty complete plan. This distinction is essential for the
later failure-freeze packet: an outage must not be interpreted as a deletion
request.

The shadow adapter's channel lifetime is the span of the supplied programmes,
and stream IDs are sorted for deterministic fixtures; neither is a host
lifecycle/ordering policy. Packet 8B owns channel identity storage and
adoption, 8C owns validation against host state and application, and 8D owns
last-good persistence and outage behavior. No external protocol or plugin
execution is introduced here.

## Packet 8C: validation, diff, and application

`teamarr/consumers/planning/validation.py` adds host-state checks on top of
the record contracts: the plan must belong to the plugin it is submitted for,
programmes must fit their channel's programme window, XMLTV channel ids must
not collide with any channel the plan will not own (core or other plugins),
and stream/group/profile hints are checked against host-supplied catalog
resolvers when available. Validation returns diagnostics; a plan with
diagnostics is never applied.

`diffing.py` compares a complete plan with only that plugin's active rows and
produces ordered intentions: `create`, `adopt` (matched by unambiguous
adoption key), `update`, `stream_order`, and `retire` for active channels the
complete plan no longer claims. An ambiguous adoption key blocks the entire
diff — the host never chooses between candidates.

`applier.py` executes an unblocked diff through the existing repositories and
channel manager: Dispatcharr create/rename/update/delete must succeed before
any local row claims success, a failed local insert after a remote create is
compensated by deleting the remote channel, retire keeps the row when the
remote delete fails so it is retried, and per-intention failures are isolated.
A `status="failed"` plan never runs the deletion diff. `dry_run=True` (or the
global `DRY_RUN` flag) returns the validated diff summary with zero writes.
`PlanApplyOutcome.to_metrics()` produces the shape recorded under the parent
run's `extra_metrics["plans"]` when planning enters the pipeline (Packet 8F).
