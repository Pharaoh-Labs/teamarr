"""In-process planning proof; no host mutations or public plugin runtime."""

from .applier import PlanApplier, PlanApplyOutcome
from .contracts import (
    ChannelPlan,
    EventSnapshot,
    MatchSnapshot,
    PlanDiagnostic,
    PlanRequest,
    PlanResult,
    ProgrammePlan,
    ProgrammeSnapshot,
    SessionSnapshot,
    SourceSnapshot,
    StreamSnapshot,
    decode_plan_request,
    decode_plan_result,
    encode_plan_request,
    encode_plan_result,
)
from .diffing import (
    PlanDiff,
    PlanIntention,
    compute_plan_diff,
    load_host_time,
    plan_field_reasons,
)
from .sources import EventGroupShadowSource, PlanSource, snapshot_event_group_match
from .validation import validate_plan

__all__ = [
    "ChannelPlan",
    "EventGroupShadowSource",
    "EventSnapshot",
    "MatchSnapshot",
    "PlanApplier",
    "PlanApplyOutcome",
    "PlanDiff",
    "PlanDiagnostic",
    "PlanIntention",
    "PlanRequest",
    "PlanResult",
    "PlanSource",
    "ProgrammePlan",
    "ProgrammeSnapshot",
    "SessionSnapshot",
    "SourceSnapshot",
    "StreamSnapshot",
    "compute_plan_diff",
    "decode_plan_request",
    "decode_plan_result",
    "encode_plan_request",
    "encode_plan_result",
    "load_host_time",
    "plan_field_reasons",
    "snapshot_event_group_match",
    "validate_plan",
]
