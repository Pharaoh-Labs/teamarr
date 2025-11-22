# Suffix Availability Indicators - UI Enhancement
**Visual indicators showing which suffixes are available for each variable**

---

## The Problem

Users need to know:
- Can I use `.next` with this variable?
- Can I use `.last` with this variable?
- Which suffix strategy does this variable use?

---

## The Solution

Add **visual suffix indicators** to each variable in the helper sidebar.

---

## Suffix Strategies (User-Friendly Labels)

```
BASE ONLY       → Team identity & season stats (e.g., team_name, league)
.last ONLY      → Game results & scores (e.g., result, score)
BASE + .next    → Betting odds (e.g., odds_spread, odds_moneyline)
ALL THREE       → Game-specific data (e.g., opponent, venue, date)
```

---

## UI Implementation

### Option 1: Inline Badges (Recommended)

Add suffix availability badge next to each variable name:

```html
<div class="variable-item" onclick="insertVariable('opponent')">
  <div class="variable-header">
    <span class="variable-name">opponent</span>
    <span class="suffix-badge badge-all" title="Available: base, .next, .last">ALL</span>
  </div>
  <div class="variable-description">Opponent full name</div>
</div>

<div class="variable-item" onclick="insertVariable('team_name')">
  <div class="variable-header">
    <span class="variable-name">team_name</span>
    <span class="suffix-badge badge-base" title="Available: base only">BASE</span>
  </div>
  <div class="variable-description">Full team name</div>
</div>

<div class="variable-item" onclick="insertVariable('result')">
  <div class="variable-header">
    <span class="variable-name">result</span>
    <span class="suffix-badge badge-last" title="Available: .last only">.last</span>
  </div>
  <div class="variable-description">Win/loss keyword</div>
</div>

<div class="variable-item" onclick="insertVariable('odds_spread')">
  <div class="variable-header">
    <span class="variable-name">odds_spread</span>
    <span class="suffix-badge badge-next" title="Available: base, .next">.next</span>
  </div>
  <div class="variable-description">Point spread</div>
</div>
```

### CSS for Badges

```css
.variable-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.variable-name {
  flex: 1;
  font-family: 'Monaco', 'Consolas', monospace;
  font-size: 13px;
  font-weight: 600;
}

.suffix-badge {
  flex: 0 0 auto;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  cursor: help;
}

.badge-base {
  background: #3b82f6;
  color: white;
}

.badge-last {
  background: #10b981;
  color: white;
}

.badge-next {
  background: #f59e0b;
  color: white;
}

.badge-all {
  background: #8b5cf6;
  color: white;
}

/* Light mode adjustments */
[data-theme="light"] .suffix-badge {
  font-weight: 600;
}
```

---

### Option 2: Suffix Dots (Minimalist)

Use colored dots to indicate suffix availability:

```html
<div class="variable-item" onclick="insertVariable('opponent')">
  <div class="variable-header">
    <span class="variable-name">opponent</span>
    <div class="suffix-dots">
      <span class="dot dot-base" title="Has base"></span>
      <span class="dot dot-next" title="Has .next"></span>
      <span class="dot dot-last" title="Has .last"></span>
    </div>
  </div>
  <div class="variable-description">Opponent full name</div>
</div>

<div class="variable-item" onclick="insertVariable('team_name')">
  <div class="variable-header">
    <span class="variable-name">team_name</span>
    <div class="suffix-dots">
      <span class="dot dot-base" title="Has base"></span>
      <span class="dot dot-inactive" title="No .next"></span>
      <span class="dot dot-inactive" title="No .last"></span>
    </div>
  </div>
  <div class="variable-description">Full team name</div>
</div>
```

### CSS for Dots

```css
.suffix-dots {
  display: flex;
  gap: 3px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  cursor: help;
}

.dot-base {
  background: #3b82f6;
}

.dot-next {
  background: #f59e0b;
}

.dot-last {
  background: #10b981;
}

.dot-inactive {
  background: var(--border-color);
  opacity: 0.3;
}
```

---

### Option 3: Enhanced Legend (Top of Sidebar)

Add a legend explaining the suffix strategies:

```html
<div class="suffix-legend">
  <div class="legend-title">Suffix Availability:</div>
  <div class="legend-items">
    <div class="legend-item">
      <span class="suffix-badge badge-base">BASE</span>
      <span class="legend-text">Team identity</span>
    </div>
    <div class="legend-item">
      <span class="suffix-badge badge-last">.last</span>
      <span class="legend-text">Results only</span>
    </div>
    <div class="legend-item">
      <span class="suffix-badge badge-next">.next</span>
      <span class="legend-text">Odds/future</span>
    </div>
    <div class="legend-item">
      <span class="suffix-badge badge-all">ALL</span>
      <span class="legend-text">Game data</span>
    </div>
  </div>
</div>
```

### CSS for Legend

```css
.suffix-legend {
  padding: 12px;
  background: var(--input-background);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  margin-bottom: 16px;
}

.legend-title {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.legend-items {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.legend-text {
  font-size: 11px;
  color: var(--text-secondary);
}
```

---

## JavaScript Enhancement

Map variables to their suffix strategy:

```javascript
// Suffix strategy mapping
const SUFFIX_STRATEGIES = {
  'BASE': [
    'team_name', 'team_abbrev', 'league', 'league_name', 'sport',
    'team_record', 'team_wins', 'team_losses', 'team_ties', 'team_win_pct',
    'playoff_seed', 'games_back', 'team_ppg', 'team_papg', 'team_rank',
    'is_ranked', 'streak', 'home_record', 'away_record', 'home_win_pct',
    'away_win_pct', 'home_streak', 'away_streak', 'last_5_record', 'last_10_record',
    'recent_form', 'pro_conference', 'pro_conference_abbrev', 'pro_division',
    'college_conference', 'college_conference_abbrev', 'conference_abbrev',
    'conference_name', 'conference_full_name', 'division_abbrev', 'division_name',
    'head_coach', 'is_national_broadcast', 'is_playoff', 'is_preseason',
    'is_ranked_matchup', 'is_regular_season', 'opponent_is_ranked'
  ],
  'LAST': [
    'opponent_score', 'overtime_text', 'result', 'result_text', 'result_verb',
    'score', 'score_diff', 'score_differential', 'score_differential_text', 'team_score'
  ],
  'NEXT': [
    'odds_details', 'odds_moneyline', 'odds_opponent_moneyline', 'odds_opponent_spread',
    'odds_over_under', 'odds_provider', 'odds_spread'
  ]
};

function getSuffixStrategy(variableName) {
  if (SUFFIX_STRATEGIES.BASE.includes(variableName)) return 'BASE';
  if (SUFFIX_STRATEGIES.LAST.includes(variableName)) return 'LAST';
  if (SUFFIX_STRATEGIES.NEXT.includes(variableName)) return 'NEXT';
  return 'ALL'; // Default: all three suffixes
}

function createVariableItemWithBadge(variable) {
  const strategy = getSuffixStrategy(variable.name);
  
  let badgeHTML = '';
  let badgeClass = '';
  let badgeText = '';
  let tooltipText = '';
  
  switch(strategy) {
    case 'BASE':
      badgeClass = 'badge-base';
      badgeText = 'BASE';
      tooltipText = 'Available: base only';
      break;
    case 'LAST':
      badgeClass = 'badge-last';
      badgeText = '.last';
      tooltipText = 'Available: .last only';
      break;
    case 'NEXT':
      badgeClass = 'badge-next';
      badgeText = '.next';
      tooltipText = 'Available: base, .next';
      break;
    case 'ALL':
      badgeClass = 'badge-all';
      badgeText = 'ALL';
      tooltipText = 'Available: base, .next, .last';
      break;
  }
  
  badgeHTML = `<span class="suffix-badge ${badgeClass}" title="${tooltipText}">${badgeText}</span>`;
  
  return `
    <div class="variable-item" onclick="insertVariable('${variable.name}')">
      <div class="variable-header">
        <span class="variable-name">${variable.name}</span>
        ${badgeHTML}
      </div>
      <div class="variable-description">${variable.description}</div>
    </div>
  `;
}
```

---

## Recommended Approach

**Combination of Option 1 + Option 3:**

1. **Add legend at top** (Option 3) - Explains the 4 strategies
2. **Add badges to each variable** (Option 1) - Shows which strategy applies
3. **Use color coding** - Visual consistency across UI

**Why:**
- Legend educates users upfront
- Badges provide quick visual reference
- Color coding creates patterns users learn quickly
- Tooltip provides detailed info on hover

---

## User Experience Flow

1. User opens template form
2. Sees suffix guide (collapsible info box)
3. Sees legend explaining 4 strategies
4. Browses variables with visual badges
5. Understands at a glance which suffixes available
6. Clicks variable to insert
7. Can manually add `.next` or `.last` if needed

---

## Mobile Considerations

On smaller screens:
- Use 2-letter badges (BA, LA, NE, AL)
- Or use dots instead of badges
- Stack legend items vertically
- Ensure touch targets are 44×44px minimum

---

## Accessibility

- Use `title` attributes for tooltips
- Ensure color contrast meets WCAG AA
- Add `aria-label` to badges
- Support keyboard navigation
- Test with screen readers

---

## Implementation Checklist

- [ ] Add suffix strategy constants to JavaScript
- [ ] Update variable rendering to include badges
- [ ] Add legend component to sidebar
- [ ] Style badges for light/dark mode
- [ ] Add tooltips with full availability info
- [ ] Test color contrast
- [ ] Test on mobile devices
- [ ] Verify keyboard navigation
- [ ] Update existing variables to show badges

---

## Example Variable Categories with Badges

**Team & Opponent** (Mostly ALL):
- opponent `ALL` - Full game context
- team_name `BASE` - Team identity
- opponent_record `ALL` - Varies per game

**Betting Lines** (Mostly BASE + .next):
- odds_spread `.next`
- odds_moneyline `.next`
- odds_over_under `.next`

**Game Results** (.last ONLY):
- result `.last`
- score `.last`
- team_score `.last`

**Date & Time** (ALL):
- game_date `ALL`
- game_time `ALL`
- days_until `ALL`

---

**Created:** 2025-11-23
**Status:** Ready for implementation
**Priority:** High - Significantly improves UX
