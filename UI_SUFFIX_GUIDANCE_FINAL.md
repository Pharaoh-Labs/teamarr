# Variable Suffix System - UI Guidance (FINAL)
**For Template Form Variable Helper Sidebar**
**Updated with correct reconciled numbers**

---

## Quick Facts

```
Base variables:  112
Total with suffixes: 237

Suffix availability:
  BASE only    → 36 variables (team identity & season stats)
  .last only   → 10 variables (game results & scores)
  BASE + .next →  7 variables (betting odds)
  ALL THREE    → 59 variables (game-specific data)
```

---

## UI Component 1: Collapsible Suffix Guide

**Placement:** Top of variable helper sidebar, before search box

```html
<!-- Variable Suffix System Guide -->
<div class="suffix-guide-box">
  <div class="suffix-guide-header" onclick="toggleSuffixGuide()">
    <span class="icon">ℹ️</span>
    <strong>Using .next and .last Suffixes</strong>
    <span class="toggle-icon">▼</span>
  </div>
  
  <div id="suffix-guide-content" class="suffix-guide-content" style="display: none;">
    <!-- Quick Reference -->
    <div class="suffix-quick-ref">
      <div class="suffix-syntax">
        <code>{variable}</code> <span class="syntax-label">Current game</span>
      </div>
      <div class="suffix-syntax">
        <code>{variable.next}</code> <span class="syntax-label">Next game</span>
      </div>
      <div class="suffix-syntax">
        <code>{variable.last}</code> <span class="syntax-label">Last game</span>
      </div>
    </div>

    <!-- Examples -->
    <div class="suffix-examples">
      <div class="example-title">Examples:</div>
      
      <div class="example-item">
        <code>{opponent}</code>
        <span class="example-arrow">→</span>
        <span class="example-output">Los Angeles Lakers</span>
      </div>
      
      <div class="example-item">
        <code>{opponent.next}</code>
        <span class="example-arrow">→</span>
        <span class="example-output">LA Clippers</span>
      </div>
      
      <div class="example-item">
        <code>{opponent.last}</code>
        <span class="example-arrow">→</span>
        <span class="example-output">Miami Heat</span>
      </div>
    </div>

    <!-- Suffix Availability -->
    <div class="suffix-availability">
      <div class="availability-title">When to use each suffix:</div>
      
      <div class="availability-item">
        <span class="suffix-badge badge-base">BASE</span>
        <span class="text">Team identity (36 vars) - e.g., team_name, league</span>
      </div>
      
      <div class="availability-item">
        <span class="suffix-badge badge-last">.last</span>
        <span class="text">Results only (10 vars) - e.g., score, result</span>
      </div>
      
      <div class="availability-item">
        <span class="suffix-badge badge-next">.next</span>
        <span class="text">Odds/future (7 vars) - e.g., odds_spread</span>
      </div>
      
      <div class="availability-item">
        <span class="suffix-badge badge-all">ALL</span>
        <span class="text">Game data (59 vars) - e.g., opponent, venue</span>
      </div>
    </div>

    <!-- Use Cases -->
    <div class="suffix-use-cases">
      <div class="use-case-title">Common use cases:</div>
      
      <div class="use-case-item">
        <strong>Pregame:</strong> 
        <code>Up next: {opponent.next} at {venue.next}</code>
      </div>
      
      <div class="use-case-item">
        <strong>Postgame:</strong> 
        <code>Final: {result_verb.last} {opponent.last} {score.last}</code>
      </div>
      
      <div class="use-case-item">
        <strong>Idle:</strong> 
        <code>Next: {opponent.next} on {game_date.next}</code>
      </div>
    </div>

    <!-- Important Note -->
    <div class="suffix-note">
      <strong>💡 Note:</strong> Each variable shows a badge indicating which suffixes it supports. Click any variable to insert it at your cursor position.
    </div>
  </div>
</div>
```

---

## UI Component 2: Variable Count Header

**Placement:** Variables section header

```html
<div class="variables-header">
  <h3>Available Variables</h3>
  <div class="variable-count">
    <span class="count-main">112 base variables</span>
    <button class="count-detail-btn" onclick="toggleSuffixBreakdown()" title="Click to see breakdown">
      (237 with suffixes)
      <span class="icon">ℹ️</span>
    </button>
  </div>
</div>

<!-- Expandable breakdown -->
<div id="suffix-breakdown-panel" class="suffix-breakdown-panel" style="display: none;">
  <div class="breakdown-title">Suffix Distribution:</div>
  <div class="breakdown-grid">
    <div class="breakdown-item">
      <span class="suffix-badge badge-base">BASE</span>
      <span class="breakdown-count">36 × 1 = 36</span>
      <span class="breakdown-desc">Team identity</span>
    </div>
    <div class="breakdown-item">
      <span class="suffix-badge badge-last">.last</span>
      <span class="breakdown-count">10 × 1 = 10</span>
      <span class="breakdown-desc">Results only</span>
    </div>
    <div class="breakdown-item">
      <span class="suffix-badge badge-next">.next</span>
      <span class="breakdown-count">7 × 2 = 14</span>
      <span class="breakdown-desc">Odds/future</span>
    </div>
    <div class="breakdown-item">
      <span class="suffix-badge badge-all">ALL</span>
      <span class="breakdown-count">59 × 3 = 177</span>
      <span class="breakdown-desc">Game data</span>
    </div>
  </div>
  <div class="breakdown-total">
    <strong>Total: 237 variable instances</strong>
  </div>
</div>
```

---

## UI Component 3: Variable Items with Badges

**Update variable rendering to include suffix badges**

```html
<!-- Example variable items -->
<div class="variable-item" onclick="insertVariable('opponent')">
  <div class="variable-header">
    <span class="variable-name">opponent</span>
    <span class="suffix-badge badge-all" title="Available: base, .next, .last">ALL</span>
  </div>
  <div class="variable-description">Opponent team full name</div>
</div>

<div class="variable-item" onclick="insertVariable('team_name')">
  <div class="variable-header">
    <span class="variable-name">team_name</span>
    <span class="suffix-badge badge-base" title="Available: base only">BASE</span>
  </div>
  <div class="variable-description">Your team's full name</div>
</div>

<div class="variable-item" onclick="insertVariable('result')">
  <div class="variable-header">
    <span class="variable-name">result</span>
    <span class="suffix-badge badge-last" title="Available: .last only">.last</span>
  </div>
  <div class="variable-description">Win/loss outcome (completed games)</div>
</div>

<div class="variable-item" onclick="insertVariable('odds_spread')">
  <div class="variable-header">
    <span class="variable-name">odds_spread</span>
    <span class="suffix-badge badge-next" title="Available: base, .next">.next</span>
  </div>
  <div class="variable-description">Point spread for betting</div>
</div>
```

---

## CSS Styling (Complete)

```css
/* ================================================================
   SUFFIX GUIDE BOX
   ================================================================ */

.suffix-guide-box {
  background: var(--card-background);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  margin-bottom: 16px;
  overflow: hidden;
}

.suffix-guide-header {
  padding: 12px 16px;
  cursor: pointer;
  user-select: none;
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--input-background);
  transition: background 0.2s;
}

.suffix-guide-header:hover {
  background: var(--input-focus-background);
}

.suffix-guide-header .toggle-icon {
  margin-left: auto;
  font-size: 12px;
  transition: transform 0.2s;
}

.suffix-guide-header.expanded .toggle-icon {
  transform: rotate(180deg);
}

.suffix-guide-content {
  padding: 16px;
  font-size: 13px;
  line-height: 1.5;
}

/* Quick Reference */
.suffix-quick-ref {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 16px;
  padding: 12px;
  background: var(--input-background);
  border-radius: 4px;
}

.suffix-syntax {
  display: flex;
  align-items: center;
  gap: 12px;
}

.suffix-syntax code {
  flex: 0 0 auto;
  min-width: 140px;
  padding: 4px 8px;
  background: var(--code-background);
  border-radius: 3px;
  font-family: 'Monaco', 'Consolas', monospace;
  font-size: 12px;
}

.syntax-label {
  flex: 1;
  color: var(--text-secondary);
  font-size: 12px;
}

/* Examples */
.suffix-examples {
  margin-bottom: 16px;
}

.example-title,
.availability-title,
.use-case-title {
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text-primary);
  font-size: 12px;
}

.example-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
  border-bottom: 1px solid var(--border-color);
}

.example-item:last-child {
  border-bottom: none;
}

.example-item code {
  flex: 0 0 auto;
  min-width: 140px;
  padding: 2px 6px;
  background: var(--code-background);
  border-radius: 3px;
  font-family: 'Monaco', 'Consolas', monospace;
  font-size: 11px;
}

.example-arrow {
  flex: 0 0 auto;
  color: var(--text-secondary);
  font-size: 14px;
}

.example-output {
  flex: 1;
  color: var(--text-secondary);
  font-size: 12px;
}

/* Suffix Availability */
.suffix-availability {
  margin-bottom: 16px;
}

.availability-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
}

.availability-item .text {
  flex: 1;
  font-size: 12px;
  color: var(--text-secondary);
}

/* Use Cases */
.suffix-use-cases {
  margin-bottom: 12px;
}

.use-case-item {
  padding: 6px 0;
  font-size: 12px;
  line-height: 1.6;
}

.use-case-item strong {
  color: var(--text-primary);
  min-width: 80px;
  display: inline-block;
}

.use-case-item code {
  padding: 2px 6px;
  background: var(--code-background);
  border-radius: 3px;
  font-family: 'Monaco', 'Consolas', monospace;
  font-size: 11px;
}

/* Important Note */
.suffix-note {
  padding: 12px;
  background: rgba(59, 130, 246, 0.1);
  border-left: 3px solid #3b82f6;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.5;
}

[data-theme="light"] .suffix-note {
  background: rgba(59, 130, 246, 0.05);
}

/* ================================================================
   VARIABLE COUNT HEADER
   ================================================================ */

.variables-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-color);
}

.variable-count {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.count-main {
  color: var(--text-primary);
  font-weight: 600;
}

.count-detail-btn {
  background: none;
  border: none;
  color: var(--text-secondary);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: 4px;
  transition: background 0.2s;
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.count-detail-btn:hover {
  background: var(--input-background);
}

.count-detail-btn .icon {
  font-size: 14px;
}

/* Suffix Breakdown Panel */
.suffix-breakdown-panel {
  background: var(--card-background);
  border: 1px solid var(--border-color);
  border-radius: 6px;
  padding: 16px;
  margin-bottom: 16px;
  animation: slideDown 0.2s ease-out;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-8px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.breakdown-title {
  font-weight: 600;
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--text-primary);
}

.breakdown-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}

@media (max-width: 768px) {
  .breakdown-grid {
    grid-template-columns: 1fr;
  }
}

.breakdown-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  background: var(--input-background);
  border-radius: 4px;
}

.breakdown-count {
  font-family: 'Monaco', 'Consolas', monospace;
  font-size: 11px;
  color: var(--text-secondary);
}

.breakdown-desc {
  font-size: 11px;
  color: var(--text-secondary);
}

.breakdown-total {
  padding-top: 12px;
  border-top: 1px solid var(--border-color);
  font-size: 13px;
  color: var(--text-primary);
  text-align: center;
}

/* ================================================================
   SUFFIX BADGES
   ================================================================ */

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
  padding: 2px 8px;
  border-radius: 3px;
  font-size: 9px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  cursor: help;
  white-space: nowrap;
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

[data-theme="light"] .badge-base {
  background: #2563eb;
}

[data-theme="light"] .badge-last {
  background: #059669;
}

[data-theme="light"] .badge-next {
  background: #d97706;
}

[data-theme="light"] .badge-all {
  background: #7c3aed;
}
```

---

## JavaScript Functions

```javascript
// Toggle suffix guide
function toggleSuffixGuide() {
  const content = document.getElementById('suffix-guide-content');
  const header = document.querySelector('.suffix-guide-header');
  
  if (content.style.display === 'none') {
    content.style.display = 'block';
    header.classList.add('expanded');
    localStorage.setItem('suffixGuideExpanded', 'true');
  } else {
    content.style.display = 'none';
    header.classList.remove('expanded');
    localStorage.setItem('suffixGuideExpanded', 'false');
  }
}

// Toggle suffix breakdown
function toggleSuffixBreakdown() {
  const panel = document.getElementById('suffix-breakdown-panel');
  if (panel.style.display === 'none') {
    panel.style.display = 'block';
    localStorage.setItem('suffixBreakdownExpanded', 'true');
  } else {
    panel.style.display = 'none';
    localStorage.setItem('suffixBreakdownExpanded', 'false');
  }
}

// Remember expansion states
document.addEventListener('DOMContentLoaded', function() {
  // Suffix guide
  const guideExpanded = localStorage.getItem('suffixGuideExpanded') === 'true';
  if (guideExpanded) {
    const content = document.getElementById('suffix-guide-content');
    const header = document.querySelector('.suffix-guide-header');
    if (content && header) {
      content.style.display = 'block';
      header.classList.add('expanded');
    }
  }
  
  // Suffix breakdown
  const breakdownExpanded = localStorage.getItem('suffixBreakdownExpanded') === 'true';
  if (breakdownExpanded) {
    const panel = document.getElementById('suffix-breakdown-panel');
    if (panel) {
      panel.style.display = 'block';
    }
  }
});

// Suffix strategy mapping (for adding badges to variables)
const SUFFIX_STRATEGIES = {
  'BASE': [
    'away_record', 'away_streak', 'away_win_pct', 'games_back', 'head_coach',
    'home_record', 'home_streak', 'home_win_pct', 'is_national_broadcast',
    'is_playoff', 'is_preseason', 'is_ranked', 'is_ranked_matchup',
    'is_regular_season', 'last_10_record', 'last_5_record', 'league',
    'league_name', 'opponent_is_ranked', 'playoff_seed', 'pro_conference',
    'pro_conference_abbrev', 'pro_division', 'recent_form', 'sport', 'streak',
    'team_abbrev', 'team_losses', 'team_name', 'team_papg', 'team_ppg',
    'team_rank', 'team_record', 'team_ties', 'team_win_pct', 'team_wins'
  ],
  'LAST': [
    'opponent_score', 'overtime_text', 'result', 'result_text', 'result_verb',
    'score', 'score_diff', 'score_differential', 'score_differential_text',
    'team_score'
  ],
  'NEXT': [
    'odds_details', 'odds_moneyline', 'odds_opponent_moneyline',
    'odds_opponent_spread', 'odds_over_under', 'odds_provider', 'odds_spread'
  ]
};

function getSuffixStrategy(variableName) {
  if (SUFFIX_STRATEGIES.BASE.includes(variableName)) return 'BASE';
  if (SUFFIX_STRATEGIES.LAST.includes(variableName)) return 'LAST';
  if (SUFFIX_STRATEGIES.NEXT.includes(variableName)) return 'NEXT';
  return 'ALL'; // Default: all three suffixes
}

function getSuffixBadgeHTML(variableName) {
  const strategy = getSuffixStrategy(variableName);
  
  const badges = {
    'BASE': '<span class="suffix-badge badge-base" title="Available: base only">BASE</span>',
    'LAST': '<span class="suffix-badge badge-last" title="Available: .last only">.last</span>',
    'NEXT': '<span class="suffix-badge badge-next" title="Available: base, .next">.next</span>',
    'ALL': '<span class="suffix-badge badge-all" title="Available: base, .next, .last">ALL</span>'
  };
  
  return badges[strategy] || badges['ALL'];
}
```

---

## Implementation Steps

1. **Add HTML to `templates/template_form.html`:**
   - Insert suffix guide box after "Available Variables" header
   - Add variable count header with breakdown panel
   - Update variable item rendering to include badges

2. **Add CSS to `static/css/style.css`:**
   - Copy all styles from above

3. **Add JavaScript to `static/js/app.js`:**
   - Copy toggle functions
   - Copy suffix strategy mapping
   - Copy badge generation function

4. **Update variable rendering:**
   - Modify the JavaScript that creates variable items
   - Add badge using `getSuffixBadgeHTML(variable.name)`

---

## User Experience Flow

1. User opens template form
2. Sees **"112 base variables (237 with suffixes) ℹ️"** header
3. Can click ℹ️ to see breakdown (36 + 10 + 14 + 177 = 237)
4. Sees collapsible suffix guide with examples
5. Browses variables, each showing a colored badge (BASE/.last/.next/ALL)
6. Understands at a glance which suffixes are available
7. Can hover over badges for detailed tooltip
8. Inserts variables with confidence

---

## Mobile Considerations

- Stack breakdown grid to single column
- Use shorter badge text on small screens (BA, LA, NE, AL)
- Ensure touch targets are 44×44px minimum
- Test collapsible sections on mobile

---

**Created:** 2025-11-23
**Status:** Ready for implementation
**Correct Numbers:** ✅ 112 base, 237 total (36/10/7/59)
