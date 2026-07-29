"""Post-processing enforcement for EPG generation.

These enforcers run after all groups have been processed to ensure
consistency across channels:

1. KeywordEnforcer: Ensures streams are on correct channels based on
   exception keywords (Spanish → Spanish channel, etc.)

2. CrossGroupEnforcer: Consolidates duplicate channels when multiple
   groups match the same event (multi-league → single-league)

3. KeywordOrderingEnforcer: Ensures main channel has lower number than
   keyword channels for the same event (main before Spanish/French)

4. find_suspect_duplicates: Detection-only safety net for channels that
   the DB unique index can't catch -- two differently-formatted streams of
   the same real game that never got the same event_id.

Usage:
    from teamarr.consumers.enforcement import (
        KeywordEnforcer,
        CrossGroupEnforcer,
        KeywordOrderingEnforcer,
    )

    # After all groups processed:
    keyword_enforcer = KeywordEnforcer(db_factory, channel_manager)
    keyword_result = keyword_enforcer.enforce()

    cross_group_enforcer = CrossGroupEnforcer(db_factory, channel_manager)
    cross_group_result = cross_group_enforcer.enforce()

    ordering_enforcer = KeywordOrderingEnforcer(db_factory, channel_manager)
    ordering_result = ordering_enforcer.enforce()
"""

from .cross_group import CrossGroupEnforcer, CrossGroupResult
from .duplicate_detector import find_suspect_duplicates
from .keywords import KeywordEnforcementResult, KeywordEnforcer
from .ordering import KeywordOrderingEnforcer, OrderingResult

__all__ = [
    "KeywordEnforcer",
    "KeywordEnforcementResult",
    "CrossGroupEnforcer",
    "CrossGroupResult",
    "KeywordOrderingEnforcer",
    "OrderingResult",
    "find_suspect_duplicates",
]
