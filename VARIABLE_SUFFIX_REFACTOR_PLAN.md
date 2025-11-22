# Variable Suffix System Refactor Plan

## ✅ STATUS: COMPLETE (2025-11-22)

All 5 phases completed. Variable suffix system fully implemented and tested.

## Goal
Enable all 227 variables to work with `.next` and `.last` suffixes for context-aware template resolution.

## Current State (2025-11-22) - ✅ COMPLETE

### Orchestrator ✅ COMPLETE
- [x] Created `_build_full_game_context()` helper
- [x] Modified `_process_event()` to build 3 contexts (current, next, last)
- [x] Modified `_create_filler_chunks()` to use helper for next/last
- [x] Fixed `template_engine` to handle `game=None` gracefully
- [x] All tests passing

### Context Structure (Now Available)
```python
context = {
    # CURRENT game (None for filler, event for actual games)
    'game': event or None,
    'team_config': team,
    'team_stats': team_stats,
    'opponent_stats': opponent_stats,
    'h2h': h2h,
    'streaks': streaks,
    'head_coach': head_coach,
    'player_leaders': player_leaders,
    'epg_timezone': epg_timezone,
    'program_datetime': datetime(...),

    # NEXT game (fully populated for all programs)
    'next_game': {
        'game': next_event,
        'opponent_stats': {...},
        'h2h': {...},
        'streaks': {...},
        'head_coach': '...',
        'player_leaders': {...}
    },

    # LAST game (fully populated for all programs)
    'last_game': {
        'game': last_event,
        'opponent_stats': {...},
        'h2h': {...},
        'streaks': {...},
        'head_coach': '...',
        'player_leaders': {...}
    }
}
```

---

## Template Engine Refactor Plan

### Phase 1: Refactor `_build_variable_dict()`

**Current**: Generates 227 variables from current game context

**Goal**: Generate 227 × 3 = 681 variables (base, .next, .last)

**Implementation**:

1. **Extract variable generation to helper method** `_build_variables_from_game_context()`
   ```python
   def _build_variables_from_game_context(
       self,
       game: dict,
       team_config: dict,
       team_stats: dict,
       opponent_stats: dict,
       h2h: dict,
       streaks: dict,
       head_coach: str,
       player_leaders: dict,
       epg_timezone: str
   ) -> Dict[str, str]:
       """Generate all 227 variables from a single game context"""
       # Copy all current logic from _build_variable_dict()
       # Return flat dict of 227 variables
   ```

2. **Modify `_build_variable_dict()` to call helper 3 times**
   ```python
   def _build_variable_dict(self, context: Dict[str, Any]) -> Dict[str, str]:
       """Build complete dictionary with base, .next, and .last variables"""
       all_variables = {}

       # Build CURRENT game variables (no suffix)
       current_vars = self._build_variables_from_game_context(
           game=context.get('game', {}) or {},
           team_config=context.get('team_config', {}),
           team_stats=context.get('team_stats', {}),
           opponent_stats=context.get('opponent_stats', {}),
           h2h=context.get('h2h', {}),
           streaks=context.get('streaks', {}),
           head_coach=context.get('head_coach', ''),
           player_leaders=context.get('player_leaders', {}),
           epg_timezone=context.get('epg_timezone', 'America/New_York')
       )

       # Add base variables (no suffix)
       all_variables.update(current_vars)

       # Build NEXT game variables (.next suffix)
       next_game = context.get('next_game', {})
       if next_game and next_game.get('game'):
           next_vars = self._build_variables_from_game_context(
               game=next_game.get('game', {}),
               team_config=context.get('team_config', {}),
               team_stats=context.get('team_stats', {}),
               opponent_stats=next_game.get('opponent_stats', {}),
               h2h=next_game.get('h2h', {}),
               streaks=next_game.get('streaks', {}),
               head_coach=next_game.get('head_coach', ''),
               player_leaders=next_game.get('player_leaders', {}),
               epg_timezone=context.get('epg_timezone', 'America/New_York')
           )
           # Add .next suffix to all variables
           for key, value in next_vars.items():
               all_variables[f"{key}.next"] = value

       # Build LAST game variables (.last suffix)
       last_game = context.get('last_game', {})
       if last_game and last_game.get('game'):
           last_vars = self._build_variables_from_game_context(
               game=last_game.get('game', {}),
               team_config=context.get('team_config', {}),
               team_stats=context.get('team_stats', {}),
               opponent_stats=last_game.get('opponent_stats', {}),
               h2h=last_game.get('h2h', {}),
               streaks=last_game.get('streaks', {}),
               head_coach=last_game.get('head_coach', ''),
               player_leaders=last_game.get('player_leaders', {}),
               epg_timezone=context.get('epg_timezone', 'America/New_York')
           )
           # Add .last suffix to all variables
           for key, value in last_vars.items():
               all_variables[f"{key}.last"] = value

       return all_variables
   ```

### Phase 2: Update `resolve()` to Handle Suffixes

**Current**: Simple string replacement `{variable}` → `value`

**Goal**: Handle `{variable}`, `{variable.next}`, `{variable.last}`

**Implementation**:

```python
def resolve(self, template: str, context: Dict[str, Any]) -> str:
    """Resolve template variables with support for .next and .last suffixes"""
    if not template:
        return ''

    # Build all variables (including suffixed ones)
    variables = self._build_variable_dict(context)

    # Replace all placeholders in template
    result = template

    # Find all {variable} or {variable.suffix} patterns
    import re
    pattern = r'\{([a-z_][a-z0-9_]*(?:\.[a-z]+)?)\}'

    for match in re.finditer(pattern, result):
        placeholder = match.group(0)  # e.g., "{opponent.next}"
        var_name = match.group(1)     # e.g., "opponent.next"

        # Look up variable value
        var_value = variables.get(var_name, '')

        # Replace in result
        result = result.replace(placeholder, str(var_value))

    return result
```

### Phase 3: Update `variables.json` Documentation

**Add suffix documentation**:

```json
{
  "categories": {
    "basic_game_info": {
      "description": "Basic game information. All variables support .next and .last suffixes.",
      "note": "Base variables are empty for filler programs. Use .next or .last for context.",
      "variables": {
        "opponent": {
          "description": "Opponent team name (current game only)",
          "example": "Los Angeles Lakers",
          "suffixes": {
            ".next": "Next scheduled opponent",
            ".last": "Last completed opponent"
          }
        },
        ...
      }
    }
  }
}
```

### Phase 4: Testing Strategy

**Test Matrix**: 4 program types × 3 suffix types = 12 test cases

| Program Type | Base Variables | .next Variables | .last Variables |
|--------------|---------------|-----------------|-----------------|
| **Game Event** | ✅ Populated (current game) | ✅ Populated (next game) | ✅ Populated (last game) |
| **Pregame Filler** | ❌ Empty (no current game) | ✅ Populated (upcoming game) | ✅ Populated (previous game) |
| **Postgame Filler** | ❌ Empty (no current game) | ✅ Populated (next game) | ✅ Populated (just finished) |
| **Idle Filler** | ❌ Empty (no current game) | ✅ Populated (next scheduled) | ✅ Populated (last completed) |

**Test Templates**:

1. **Game Event**:
   ```
   {opponent} @ {venue}
   Next: {opponent.next} on {game_date.next}
   Last: vs {opponent.last} ({last_game_result})
   ```

2. **Pregame**:
   ```
   Pregame Show
   Up Next: {opponent.next} at {game_time.next}
   Last Game: {opponent.last} - {last_game_result}
   ```

3. **Postgame**:
   ```
   Postgame Wrap
   Final: {opponent.last} {final_score.last}
   Next Up: {opponent.next} on {game_date.next}
   ```

4. **Idle**:
   ```
   {team_name} Content
   Next Game: {opponent.next} on {game_date.next} at {game_time.next}
   Last Game: {opponent.last} on {game_date.last} - {last_game_result}
   ```

### Phase 5: Variable Audit

**Ensure all 227 variables have proper data sources**:

- [x] Basic game info (home_team, away_team, venue) - from ESPN event
- [x] Team stats (team_record, team_ppg) - from ESPN stats API
- [x] Opponent stats (opponent_ppg, opponent_rank) - from ESPN stats API
- [x] H2H data (season_series, rematch) - calculated from schedule
- [x] Streaks (home_streak, last_5_record) - calculated from schedule
- [x] Coach (head_coach) - from roster API
- [x] Player leaders (top_scorer_name, etc.) - extracted from game data
- [x] Broadcasts (broadcast_network) - from ESPN event
- [x] Odds (spread, moneyline) - from scoreboard API
- [x] Game status (game_status, period) - from ESPN event
- [x] Date/time variables - from event date with timezone conversion
- [x] Playoff series - from ESPN event
- [x] Attendance - from ESPN event

---

## Implementation Checklist

### Phase 1: Extract Variable Generation ✅ COMPLETE
- [x] Create `_build_variables_from_game_context()` helper
- [x] Move all variable generation logic from `_build_variable_dict()` to helper
- [x] Test helper returns 227 variables

### Phase 2: Build 3 Variable Sets ✅ COMPLETE
- [x] Modify `_build_variable_dict()` to call helper 3 times
- [x] Add base variables (no suffix)
- [x] Add .next variables (with suffix)
- [x] Add .last variables (with suffix)
- [x] Test returns 681 total variables

### Phase 3: Update Resolver ✅ COMPLETE
- [x] Add regex pattern matching for suffixes
- [x] Update `resolve()` to handle suffixed variables
- [x] Test with all suffix combinations

### Phase 4: Documentation ✅ COMPLETE
- [x] Update `variables.json` with suffix documentation
- [x] Add examples for each suffix type
- [x] Document behavior for each program type

### Phase 5: Testing ✅ COMPLETE
- [x] Test game events (all 3 contexts populated)
- [x] Test pregame filler (base empty, next/last populated)
- [x] Test postgame filler (base empty, next/last populated)
- [x] Test idle filler (base empty, next/last populated)
- [x] Verify all 227 variables work with .next
- [x] Verify all 227 variables work with .last
- [x] Test edge cases (no next game, no last game)

---

## Expected Results

### Before Refactor
```
Base variables: 227
Total variables: 227
Suffixes: None
```

### After Refactor
```
Base variables: 227 (empty for filler, populated for games)
.next variables: 227 (always populated when next game exists)
.last variables: 227 (always populated when last game exists)
Total variables: 681
```

### Example Variable Counts by Program Type

**Game Event** (Celtics vs Lakers on Jan 15):
```
opponent = "Los Angeles Lakers"           (current game)
opponent.next = "LA Clippers"              (game on Jan 17)
opponent.last = "Miami Heat"               (game on Jan 13)
```

**Pregame** (6 PM before Lakers game):
```
opponent = ""                              (no current game - it's filler)
opponent.next = "Los Angeles Lakers"       (game at 7 PM)
opponent.last = "Miami Heat"               (game on Jan 13)
```

**Postgame** (10 PM after Lakers game):
```
opponent = ""                              (no current game - it's filler)
opponent.next = "LA Clippers"              (game on Jan 17)
opponent.last = "Los Angeles Lakers"       (just finished)
```

**Idle** (Jan 16, no game today):
```
opponent = ""                              (no current game)
opponent.next = "LA Clippers"              (game on Jan 17)
opponent.last = "Los Angeles Lakers"       (game on Jan 15)
```

---

## Breaking Changes

**None** - Fully backward compatible!

- ✅ Existing templates continue working (base variables unchanged)
- ✅ New templates can use .next and .last suffixes
- ✅ No database changes needed
- ✅ No API changes needed

---

## Performance Considerations

### API Calls Impact
**Before**: ~2-3 API calls per game event
**After**: ~6-9 API calls per game event (3x for current, next, last)

**Mitigation**:
- We already have caching system in place (schedule_cache, team_stats_cache, h2h_cache)
- Most next/last games are from extended_events (already fetched)
- Only additional cost is opponent_stats fetching
- Can add specific caching for next/last opponent stats

### Memory Impact
**Before**: ~227 variables per program
**After**: ~681 variables per program

**Impact**: Minimal - variables are strings, total size ~50-100KB per program

### CPU Impact
**Before**: 1 variable generation pass
**After**: 3 variable generation passes

**Impact**: Minimal - variable generation is fast (~10ms), 3x = ~30ms

---

## Risk Assessment

### Low Risk
- ✅ Backward compatible (existing templates work)
- ✅ Isolated to template_engine.py (no ripple effects)
- ✅ Well-tested orchestrator foundation
- ✅ Clear rollback path (revert template_engine.py)

### Medium Risk
- ⚠️ Increased API calls (mitigated by caching)
- ⚠️ More complex variable lookup (mitigated by dict lookup O(1))

### High Risk
- ❌ None identified

---

## Success Criteria

1. ✅ All 227 variables work with no suffix (current game)
2. ✅ All 227 variables work with .next suffix
3. ✅ All 227 variables work with .last suffix
4. ✅ Base variables empty for filler programs
5. ✅ Existing templates continue working unchanged
6. ✅ New templates can use all suffixes
7. ✅ EPG generation completes without errors
8. ✅ All 4 program types generate correctly
9. ✅ Performance acceptable (<5 seconds per team)

---

## Timeline Estimate

- Phase 1 (Extract helper): 30 minutes
- Phase 2 (3 variable sets): 30 minutes
- Phase 3 (Update resolver): 15 minutes
- Phase 4 (Documentation): 30 minutes
- Phase 5 (Testing): 60 minutes

**Total**: ~2.5 hours

---

Last Updated: 2025-11-22
Status: Ready to implement
