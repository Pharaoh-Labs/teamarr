"""Event Group Processor - orchestrates the full event-based EPG flow.

Connects stream matching to channel lifecycle:
1. Load group config from database
2. Fetch M3U streams from Dispatcharr
3. Match streams to events (the matcher fetches events itself, per league)
4. Create/update channels via ChannelLifecycleService
5. Generate XMLTV EPG
6. Optionally push EPG to Dispatcharr

This is the main entry point for event-based EPG generation.

Package layout (iua3.7):
- processor.py       — EventGroupProcessor coordinator + convenience functions
- results.py         — result dataclasses (processing/batch/preview/enforcement)
- stream_fetcher.py  — M3U stream fetching/filtering + known-league lookup
- matching.py        — stream→event matching, EPG index, feed/segment expansion
- team_filter.py     — team include/exclude filtering + filtered-channel cleanup
- persistence.py     — matched/failed stream persistence for run analysis
- xmltv.py           — XMLTV + filler rendering and per-group storage
- preview.py         — preview path (match without channel/EPG side effects)
"""

from teamarr.core import SEASON_POSTSEASON

from .processor import (
    EventGroupProcessor,
    preview_event_group,
    process_all_event_groups,
)
from .results import (
    BatchProcessingResult,
    EnforcementStepResult,
    PreviewResult,
    PreviewStream,
    ProcessingResult,
)

__all__ = [
    "SEASON_POSTSEASON",
    "BatchProcessingResult",
    "EnforcementStepResult",
    "EventGroupProcessor",
    "PreviewResult",
    "PreviewStream",
    "ProcessingResult",
    "preview_event_group",
    "process_all_event_groups",
]
