---
title: Olympic Hockey
parent: Research Notes
nav_order: 2
docs_version: "2.7.0"
---

# Olympic Hockey - ESPN Provider Research

**Date:** 2026-02-04
**Status:** FEASIBLE - Ready for implementation
**Related Issues:** #88, #122
**Parent Epic:** `teamarrv2-ia2`

## Summary

ESPN has full API support for 2026 Winter Olympics (Milano Cortina) ice hockey. Implementation is straightforward - uses same endpoint pattern as other hockey leagues.

## API Findings

### Endpoints Confirmed Working

```
# Men's Ice Hockey
https://site.api.espn.com/apis/site/v2/sports/hockey/olympics-mens-ice-hockey/scoreboard
League ID: 20146

# Women's Ice Hockey
https://site.api.espn.com/apis/site/v2/sports/hockey/olympics-womens-ice-hockey/scoreboard
League ID: 20147
```

### 2026 Winter Olympics Data

**Men's Hockey:**
- **Events:** 30 games
- **Teams:** 13 countries (CAN, USA, FIN, SWE, CZE, GER, SUI, SVK, FRA, LAT, DEN, ITA + TBD)
- **Date Range:** Feb 11 - Feb 22, 2026
- **Venues:** Milano Santagiulia Ice Hockey Arena

**Women's Hockey:**
- **Events:** 28 games
- **Teams:** 11 countries (CAN, USA, FIN, SWE, CZE, GER, SUI, FRA, JPN, ITA + TBD)
- **Date Range:** Feb 5 - Feb 20, 2026

### Team ID Structure

Teams use country abbreviations consistently:
- USA (id: 79), Canada (id: 16), Finland (id: 25), Sweden (id: 71)
- Note: Some team IDs differ between men's/women's (e.g., Italy: 47841 vs 48105)
- TBD placeholder teams exist (id: -2) for undetermined playoff matchups

### Event Data Structure

```json
{
  "id": "401845663",
  "date": "2026-02-11T15:40Z",
  "shortName": "FIN VS SVK",
  "competitions": [{
    "type": {"abbreviation": "QRR"},
    "venue": {"fullName": "Milano Santagiulia Ice Hockey Arena"},
    "neutralSite": true,
    "competitors": [
      {"team": {"abbreviation": "SVK", "displayName": "Slovakia"}},
      {"team": {"abbreviation": "FIN", "displayName": "Finland"}}
    ]
  }]
}
```

## Implementation Plan

### Required Changes

1. **Schema** (`teamarr/database/schema.sql`):
   - Add `olympics-mens-ice-hockey` and `olympics-womens-ice-hockey` to leagues table
   - Sport: `hockey`, Provider: `espn`

2. **League Mappings** (if aliases needed):
   - Map common stream names like "Olympic Hockey", "Olympics Ice Hockey"

3. **No Provider Changes Required**:
   - ESPN provider already handles hockey sport correctly
   - Scoreboard/teams endpoints use identical pattern

### Stream Matching Considerations

Typical IPTV stream naming patterns:
- `USA: Olympic Hockey | USA vs CAN`
- `Olympics | Ice Hockey Men | Finland vs Sweden`
- `2026 Winter Olympics | Hockey`

Need to observe actual M3U data during Olympics to tune regex patterns.

## Testing Strategy

1. Add leagues to schema
2. Run cache refresh (`./dev.sh --update-cache`)
3. Verify teams appear in cache
4. Create test event group for Olympic hockey
5. Verify scoreboard data pulls correctly

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| No NHL players (no release) | Medium | ESPN data still valid, affects roster quality |
| TBD teams in knockouts | Low | Standard handling, events update when determined |
| Stream naming unknown | Medium | Add common aliases, refine during Olympics |

## Timeline

- **Feb 5:** Women's hockey begins
- **Feb 11:** Men's hockey begins
- **Feb 20:** Women's gold medal
- **Feb 22:** Men's gold medal

## Recommendation

**Proceed with implementation immediately.** Low effort, high value for users wanting Olympics coverage. Core functionality is identical to existing hockey leagues.

## Future: IIHF World Championships

Same ESPN pattern likely works for:
- `iihf-world-championship` (if exists)
- `iihf-world-juniors` (if exists)

Research these separately after Olympics implementation.
