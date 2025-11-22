# Variables.JSON Issues Report
**Generated:** 2025-11-23
**Status:** Requires Updates

---

## Summary

The `config/variables.json` file is **out of sync** with the variable audit implementation. It contains:
- ❌ 31 deleted variables that should be removed
- ❌ 20 legacy variables replaced by suffix system
- ❌ 6 renamed variables still using old names

**Total variables to remove:** 51
**Total variables to rename:** 6
**Current count:** 184 variables
**Target count:** 133 variables (184 - 51)

---

## Issue 1: Renamed Variables (6 variables)

These variables were renamed in the code but still use OLD names in JSON:

| Old Name (in JSON) | New Name (in code) | Status |
|-------------------|-------------------|--------|
| `matchup` | `matchup_abbrev` | ❌ Needs rename |
| `moneyline` | `odds_moneyline` | ❌ Needs rename |
| `opponent_moneyline` | `odds_opponent_moneyline` | ❌ Needs rename |
| `over_under` | `odds_over_under` | ❌ Needs rename |
| `spread` | `odds_spread` | ❌ Needs rename |
| `opponent_spread_odds` | `odds_opponent_spread` | ❌ Needs rename |

**Action:** Update the `name` field for these 6 variables in variables.json

---

## Issue 2: Deleted Variables (31 variables)

These variables were explicitly deleted during the audit but are still in JSON:

### Boolean Helpers (9 variables)
- `has_win_streak`
- `has_loss_streak`
- `has_over_under`
- `has_spread`
- `is_favorite`
- `is_underdog`
- `is_final`
- `is_overtime`
- `has_attendance`

### Redundant/Duplicates (4 variables)
- `win_streak`
- `loss_streak`
- `streak_count`
- `streak_type`

### Game Summary (2 variables)
- `game_summary`
- `game_summary_text`

### Countdown (2 variables)
- `hours_until`
- `minutes_until`

### Other Deleted (14 variables)
- `game_status`
- `period`
- `period_short`
- `season_year`
- `spread_category`
- `spread_category_text`
- `spread_odds`
- `is_conference_game`
- `is_division_game`
- `is_rivalry`
- `was_favorite_at_open`
- `opponent_was_favorite_at_open`
- `rematch_winner`
- `rematch_loser`

**Action:** REMOVE these 31 variables from variables.json

---

## Issue 3: Legacy Context Variables (20 variables)

These "next_*" and "last_*" variables are NOT set in code. They've been replaced by the suffix system (e.g., `{opponent.next}` instead of `{next_opponent}`).

### Next Game Context (11 variables)
- `next_opponent`
- `next_opponent_record`
- `next_date`
- `next_time`
- `next_datetime`
- `next_venue`
- `next_matchup`
- `next_game_date`
- `next_game_time`
- `next_game_home_team_record`
- `next_game_away_team_record`

### Last Game Context (9 variables)
- `last_opponent`
- `last_opponent_record`
- `last_date`
- `last_result`
- `last_score`
- `last_score_abbrev`
- `last_matchup`
- `last_game_home_team_record`
- `last_game_away_team_record`

**Rationale:** The suffix system provides these via `{variable.next}` and `{variable.last}` syntax. The standalone "next_*" and "last_*" variables are obsolete.

**Action:** REMOVE these 20 variables from variables.json

---

## Expected Results After Fix

### Variable Counts
```
Current base variables:     184
Variables to remove:         51
Variables to rename:          6 (no count change)
───────────────────────────────
New base variable count:    133
```

### Suffix Distribution (recalculated)
```
BASE only:           41 variables =  41 instances
BASE + .next:         7 variables =  14 instances
.last only:          10 variables =  10 instances
ALL THREE:           75 variables = 225 instances  (was 126)
───────────────────────────────────────────────────
TOTAL:              133 variables = 290 instances  (was 443)
```

**Note:** The 443 count was inflated due to legacy variables being documented.

---

## Recommended Actions

### Action 1: Rename Variables
Update the `name` field for 6 variables:
1. Find each old name in variables.json
2. Change `"name": "old_name"` to `"name": "new_name"`
3. Keep all other fields unchanged

### Action 2: Delete Variables
Remove 51 variable entries from the `variables` array:
- 31 deleted audit variables
- 20 legacy context variables

### Action 3: Update Metadata
Update counts in variables.json header:
- `base_variables`: 184 → 133
- `total_variables`: 443 → 290
- Update suffix system counts

### Action 4: Verify
Run verification script to confirm:
- All code variables documented
- No extra variables in JSON
- Counts match expectations

---

## Impact

**Benefits:**
- JSON accurately reflects implemented variables
- No confusion from deleted/legacy variables
- Cleaner documentation for template authors
- Correct variable counts

**No Breaking Changes:**
- Variables.json is documentation only
- Code functionality unchanged
- Existing templates continue working

---

**Report Generated:** 2025-11-23
**Next Step:** Apply fixes to variables.json
