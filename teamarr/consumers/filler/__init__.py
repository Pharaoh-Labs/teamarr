"""Filler generation package.

Team filler: Full pregame/postgame/idle with .next/.last suffix support.
Event filler: Simpler pregame/postgame for single-event channels.

Both share:
- time_blocks utilities for 6-hour alignment
- FillerTemplate for template structure
- TemplateResolver for variable substitution
"""

from .event_filler import (
    EventFillerConfig,
    EventFillerGenerator,
    EventFillerOptions,
    EventFillerResult,
    template_to_event_filler_config,
)
from .generator import FillerGenerator
from .types import (
    ConditionalFillerTemplate,
    FillerConfig,
    FillerOptions,
    FillerTemplate,
    FillerType,
    OffseasonFillerTemplate,
)

__all__ = [
    # Team filler
    "FillerGenerator",
    "FillerConfig",
    "FillerOptions",
    # Event filler
    "EventFillerGenerator",
    "EventFillerConfig",
    "EventFillerOptions",
    "EventFillerResult",
    "template_to_event_filler_config",
    # Shared types
    "FillerTemplate",
    "FillerType",
    "ConditionalFillerTemplate",
    "OffseasonFillerTemplate",
]
