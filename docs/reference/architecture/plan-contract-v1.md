# In-process plan contract v1 (Packet 8A)

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
