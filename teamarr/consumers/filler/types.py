"""Filler generation types and configuration.

Re-exports from teamarr.core.filler_types for backward compatibility.
Types are defined in core to maintain proper layer isolation.
"""

from teamarr.core.filler_types import (
    FillerConfig,
    FillerOptions,
    FillerTemplate,
    FillerType,
    OffseasonFillerTemplate,
    legacy_conditional_to_rows,
)

__all__ = [
    "FillerType",
    "FillerTemplate",
    "OffseasonFillerTemplate",
    "FillerConfig",
    "FillerOptions",
    "legacy_conditional_to_rows",
]
