"""In-process planning proof; no host mutations or public plugin runtime."""

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
from .sources import EventGroupShadowSource, PlanSource, snapshot_event_group_match

__all__ = [
    "ChannelPlan",
    "EventGroupShadowSource",
    "EventSnapshot",
    "MatchSnapshot",
    "PlanDiagnostic",
    "PlanRequest",
    "PlanResult",
    "PlanSource",
    "ProgrammePlan",
    "ProgrammeSnapshot",
    "SessionSnapshot",
    "SourceSnapshot",
    "StreamSnapshot",
    "decode_plan_request",
    "decode_plan_result",
    "encode_plan_request",
    "encode_plan_result",
    "snapshot_event_group_match",
]
