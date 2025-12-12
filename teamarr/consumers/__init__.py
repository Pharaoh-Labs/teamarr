"""Consumer layer - EPG generation, matching, channels."""

from teamarr.consumers.event_epg import (
    EventChannelInfo,
    EventEPGGenerator,
    EventEPGOptions,
)
from teamarr.consumers.event_matcher import EventMatcher
from teamarr.consumers.multi_league_matcher import (
    BatchMatchResult,
    MultiLeagueMatcher,
    StreamMatchResult,
)
from teamarr.consumers.orchestrator import GenerationResult, Orchestrator
from teamarr.consumers.single_league_matcher import MatchResult, SingleLeagueMatcher
from teamarr.consumers.team_epg import TeamConfig, TeamEPGGenerator, TeamEPGOptions

__all__ = [
    # Stream matching
    "MatchResult",
    "SingleLeagueMatcher",
    "BatchMatchResult",
    "MultiLeagueMatcher",
    "StreamMatchResult",
    # Event-based EPG
    "EventChannelInfo",
    "EventEPGGenerator",
    "EventEPGOptions",
    "EventMatcher",
    # Team-based EPG
    "GenerationResult",
    "Orchestrator",
    "TeamConfig",
    "TeamEPGGenerator",
    "TeamEPGOptions",
]
