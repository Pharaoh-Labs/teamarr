"""Internal generation-pipeline contracts (#830).

This package exists to make core generation orchestration explicit and
testable. **It is not a public extension point.** The eventual plugin ABI uses
serialized request/response records, not these Python classes — see the plugin
architecture plan, section 2.3.

``teamarr/consumers/generation.py`` remains the public composition root and
compatibility facade; everything callers import stays importable from there.
"""

from teamarr.consumers.generation_pipeline.models import (
    CallbackCancellationToken,
    CancellationToken,
    GenerationCancelled,
    GenerationContext,
    GenerationResult,
    GenerationSettingsSnapshot,
    ProgressCallback,
    ProgressReporter,
    ProgressUpdate,
    legacy_progress_reporter,
)
from teamarr.consumers.generation_pipeline.runner import GenerationStage, StageRunner

__all__ = [
    "CallbackCancellationToken",
    "CancellationToken",
    "GenerationCancelled",
    "GenerationContext",
    "GenerationResult",
    "GenerationSettingsSnapshot",
    "GenerationStage",
    "ProgressCallback",
    "ProgressReporter",
    "ProgressUpdate",
    "StageRunner",
    "legacy_progress_reporter",
]
