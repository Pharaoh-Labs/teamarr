---
title: Detection Library
parent: Architecture
grand_parent: Technical Reference
nav_order: 7
---

# Detection Library

The Detection Library centralizes all pattern-based stream-detection configuration,
making the built-in keyword lists user-configurable while preserving sensible
defaults. It has shipped and is configured in the UI at
[Matching → Custom Rules](../../guide/matching/index#custom-rules); the
implemented service is documented in
[Detection Keyword Service](detection-keywords).

## Key Architecture Decision: Separate Flows Per Event Type

```
Stream → Detect Event Type → Route to specific flow

TEAM_VS_TEAM:
  custom_regex_teams → extract team1/team2

EVENT_CARD (combat sports):
  custom_regex_fighters → extract fighter1/fighter2

FIELD_EVENT (golf, tennis, racing):
  custom_regex_competitors → extract competitor(s)
```

**Rationale**: Using `team1/team2` for fighters is semantically sloppy. Each sport category has distinct patterns and the UI can show relevant fields per event type.

For the pattern categories, service accessors, and API endpoints, see
[Detection Keyword Service](detection-keywords).
