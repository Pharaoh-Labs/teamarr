# Variable Suffix System - UI Guidance
**For Template Form Variable Helper Sidebar**

---

## Recommended Placement

Add this as a collapsible info box at the top of the variable helper sidebar in `templates/template_form.html`, before the search box.

---

## UI Component HTML

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
        <code>{variable}</code> - Current game
      </div>
      <div class="suffix-syntax">
        <code>{variable.next}</code> - Next game
      </div>
      <div class="suffix-syntax">
        <code>{variable.last}</code> - Last game
      </div>
    </div>

    <!-- Examples -->
    <div class="suffix-examples">
      <div class="example-title">Examples:</div>
      
      <div class="example-item">
        <code>{opponent}</code>
        <span class="example-output">Los Angeles Lakers</span>
      </div>
      
      <div class="example-item">
        <code>{opponent.next}</code>
        <span class="example-output">LA Clippers</span>
      </div>
      
      <div class="example-item">
        <code>{opponent.last}</code>
        <span class="example-output">Miami Heat</span>
      </div>
    </div>

    <!-- Suffix Availability -->
    <div class="suffix-availability">
      <div class="availability-title">Suffix Availability:</div>
      
      <div class="availability-item">
        <span class="badge badge-base">BASE</span>
        <span class="text">Team identity (name, league, record)</span>
      </div>
      
      <div class="availability-item">
        <span class="badge badge-last">LAST</span>
        <span class="text">Results (score, result, overtime)</span>
      </div>
      
      <div class="availability-item">
        <span class="badge badge-next">BASE+NEXT</span>
        <span class="text">Odds (spread, moneyline, over/under)</span>
      </div>
      
      <div class="availability-item">
        <span class="badge badge-all">ALL</span>
        <span class="text">Game data (opponent, date, venue)</span>
      </div>
    </div>

    <!-- Use Cases -->
    <div class="suffix-use-cases">
      <div class="use-case-title">Common Use Cases:</div>
      
      <div class="use-case-item">
        <strong>Pregame:</strong> <code>{opponent.next} at {venue.next}</code>
      </div>
      
      <div class="use-case-item">
        <strong>Postgame:</strong> <code>{result_verb.last} {opponent.last} {score.last}</code>
      </div>
      
      <div class="use-case-item">
        <strong>Idle:</strong> <code>Next: {opponent.next} on {game_date.next}</code>
      </div>
    </div>
  </div>
</div>
```

---

## CSS Styling

```css
/* Variable Suffix Guide Box */
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
  gap: 6px;
  margin-bottom: 16px;
  padding: 12px;
  background: var(--input-background);
  border-radius: 4px;
}

.suffix-syntax {
  display: flex;
  align-items: center;
}

.suffix-syntax code {
  flex: 1;
  padding: 4px 8px;
  background: var(--code-background);
  border-radius: 3px;
  font-family: 'Monaco', 'Consolas', monospace;
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
  padding: 2px 6px;
  background: var(--code-background);
  border-radius: 3px;
  font-family: 'Monaco', 'Consolas', monospace;
  font-size: 11px;
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
  padding: 4px 0;
}

.availability-item .badge {
  flex: 0 0 auto;
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
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

.availability-item .text {
  flex: 1;
  font-size: 12px;
  color: var(--text-secondary);
}

/* Use Cases */
.suffix-use-cases {
  margin-bottom: 0;
}

.use-case-item {
  padding: 6px 0;
  font-size: 12px;
}

.use-case-item strong {
  color: var(--text-primary);
  min-width: 70px;
  display: inline-block;
}

.use-case-item code {
  padding: 2px 6px;
  background: var(--code-background);
  border-radius: 3px;
  font-family: 'Monaco', 'Consolas', monospace;
  font-size: 11px;
}
```

---

## JavaScript

```javascript
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

// Remember expansion state
document.addEventListener('DOMContentLoaded', function() {
  const isExpanded = localStorage.getItem('suffixGuideExpanded') === 'true';
  if (isExpanded) {
    document.getElementById('suffix-guide-content').style.display = 'block';
    document.querySelector('.suffix-guide-header').classList.add('expanded');
  }
});
```

---

## Simplified Version (Minimal)

If you want something more compact:

```html
<div class="suffix-hint">
  <strong>💡 Tip:</strong> Add <code>.next</code> or <code>.last</code> to most variables.
  <br>
  Example: <code>{opponent}</code> → <code>{opponent.next}</code> or <code>{opponent.last}</code>
  <br>
  <a href="#" onclick="showSuffixExamples(); return false;">See examples</a>
</div>
```

---

## Where to Add in Template Form

Insert after line ~440 in `templates/template_form.html`, right after:
```html
<div class="variables-section">
  <h3>Available Variables</h3>
```

Add before the search box:
```html
  <!-- ADD SUFFIX GUIDE HERE -->
  <div class="suffix-guide-box">
    ...
  </div>
  
  <!-- Search box follows -->
  <div class="search-box">
```

---

## Alternative: Tooltip on Variable Hover

Add tooltip to each variable in the helper:

```javascript
function createVariableTooltip(variable) {
  let tooltip = `Click to insert {${variable.name}}`;
  
  // Check suffix availability
  const suffixInfo = getSuffixAvailability(variable.name);
  if (suffixInfo.hasNext || suffixInfo.hasLast) {
    tooltip += '\n\nAlso available:';
    if (suffixInfo.hasNext) tooltip += `\n• {${variable.name}.next}`;
    if (suffixInfo.hasLast) tooltip += `\n• {${variable.name}.last}`;
  }
  
  return tooltip;
}
```

---

## Mobile-Friendly Version

For smaller screens, use an icon-based approach:

```html
<div class="suffix-info-icon" title="Variable Suffix Help" onclick="showSuffixModal()">
  <span>ℹ️</span>
</div>
```

Then show guidance in a modal instead of inline.

---

## Recommended Implementation

**Best approach:** Collapsible info box at top of variable helper

**Why:**
- Always visible but not intrusive
- Users can expand when needed
- Remembers state across sessions
- Provides quick reference while writing templates
- Shows examples in context

**Priority:** High - This significantly improves UX for template authors

---

## Testing Checklist

- [ ] Guide displays correctly in light/dark mode
- [ ] Toggle animation smooth
- [ ] State persists across page loads
- [ ] Code examples are copyable
- [ ] Responsive on mobile screens
- [ ] Accessible (keyboard navigation, screen readers)
- [ ] Examples match actual variable behavior

---

**Created:** 2025-11-23
**Status:** Ready for implementation
**Location:** Template form variable helper sidebar
