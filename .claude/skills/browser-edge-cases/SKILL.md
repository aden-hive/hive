---
name: browser-edge-cases
description: SOP for debugging browser automation failures on complex websites. Use when browser tools fail on specific sites like LinkedIn, Twitter/X, SPAs, or sites with Shadow DOM.
license: MIT
---

# Browser Tool Edge Cases

Standard Operating Procedure for debugging and fixing browser automation failures on complex websites.

## When to Use This Skill

- `browser_scroll` succeeds but page doesn't move
- `browser_click` succeeds but no action triggered
- `browser_type` text disappears or doesn't work
- `browser_snapshot` hangs or returns stale content
- `browser_navigate` loads wrong content

## SOP: Debugging Browser Tool Failures

### Phase 1: Reproduce & Isolate

```
1. Create minimal test case demonstrating failure
2. Test against simple site (example.com) to verify tool works
3. Test against problematic site to confirm issue
```

**Quick isolation test:**
```python
# Test 1: Does the tool work at all?
await browser_navigate(tab_id, "https://example.com")
result = await browser_scroll(tab_id, "down", 100)
# Should work on simple sites

# Test 2: Does it fail on the problematic site?
await browser_navigate(tab_id, "https://linkedin.com/feed")
result = await browser_scroll(tab_id, "down", 100)
# If this fails but example.com works → site-specific edge case
```

### Phase 2: Analyze Root Cause

**Step 2a: Check console for errors**
```python
console = await browser_console(tab_id)
# Look for: CSP violations, React errors, JavaScript exceptions
```

**Step 2b: Inspect DOM structure**
```python
html = await browser_html(tab_id)
snapshot = await browser_snapshot(tab_id)
# Look for:
# - Nested scrollable divs (overflow: scroll/auto)
# - Shadow DOM roots
# - iframes
# - Custom widgets
```

**Step 2c: Identify the pattern**

| Symptom | Likely Cause | Check |
|---------|--------------|-------|
| Scroll doesn't move | Nested scroll container | Look for `overflow: scroll` divs |
| Click no effect | Element covered | Check `getBoundingClientRect` vs viewport |
| Type clears | Autocomplete/React | Check for event listeners on input; try `browser_type_focused` |
| Snapshot hangs | Huge DOM | Check node count in snapshot |
| Snapshot stale | SPA hydration | Wait after navigation |

### Phase 3: Implement Multi-Layer Fix

**Pattern: Always have fallbacks**

```python
async def robust_operation(tab_id):
    # Method 1: Primary approach
    try:
        result = await primary_method(tab_id)
        if verify_success(result):
            return result
    except Exception:
        pass

    # Method 2: CDP fallback
    try:
        result = await cdp_fallback(tab_id)
        if verify_success(result):
            return result
    except Exception:
        pass

    # Method 3: JavaScript fallback
    return await javascript_fallback(tab_id)
```

**Pattern: Always add timeouts**

```python
# Bad - can hang forever
result = await browser_snapshot(tab_id)

# Good - fails fast with useful error
try:
    result = await browser_snapshot(tab_id, timeout_s=10.0)
except asyncio.TimeoutError:
    # Handle timeout gracefully
    result = await fallback_snapshot(tab_id)
```

### Phase 4: Verify Fix

```
1. Run against problematic site → should work
2. Run against simple site → should still work (regression check)
3. Document in registry.md
```

## Pattern Library

### P1: Nested Scrollable Containers

**Sites:** LinkedIn, Twitter/X, any SPA with scrollable feeds

**Detection:**
```javascript
// Find largest scrollable container
const candidates = [];
document.querySelectorAll('*').forEach(el => {
    const style = getComputedStyle(el);
    if (style.overflow.includes('scroll') || style.overflow.includes('auto')) {
        const rect = el.getBoundingClientRect();
        if (rect.width > 100 && rect.height > 100) {
            candidates.push({el, area: rect.width * rect.height});
        }
    }
});
candidates.sort((a, b) => b.area - a.area);
return candidates[0]?.el;
```

**Fix:** Dispatch scroll events at container's center, not viewport center.

### P2: Element Covered by Overlay

**Sites:** Modals, tooltips, SPAs with loading overlays

**Detection:**
```javascript
const rect = element.getBoundingClientRect();
const centerX = rect.left + rect.width / 2;
const centerY = rect.top + rect.height / 2;
const topElement = document.elementFromPoint(centerX, centerY);
return topElement === element || element.contains(topElement);
```

**Fix:** Wait for overlay to disappear, or use JavaScript click.

### P3: React Synthetic Events

**Sites:** React SPAs, modern web apps

**Detection:** If CDP click doesn't trigger handler but manual click works.

**Fix:** Use JavaScript click as primary:
```javascript
element.click();
```

### P4: Huge DOM / Accessibility Tree

**Sites:** LinkedIn, Facebook, Twitter (feeds with 1000s of nodes)

**Detection:**
```javascript
document.querySelectorAll('*').length > 5000
```

**Fix:**
1. Add timeout to snapshot operation
2. Truncate tree at 2000 nodes
3. Fall back to DOM-based snapshot if accessibility tree too large

### P5: SPA Hydration Delay

**Sites:** React, Vue, Angular SPAs after navigation

**Detection:**
```javascript
// Check if React app has hydrated
document.querySelector('[data-reactroot]') ||
document.querySelector('[data-reactid]')
```

**Fix:** Wait for specific selector after navigation:
```python
await browser_navigate(tab_id, url, wait_until="load")
await browser_wait(tab_id, selector='[data-testid="content"]', timeout_ms=5000)
```

### P6: Shadow DOM

**Sites:** Components using Shadow DOM, Lit elements

**Detection:**
```javascript
document.querySelectorAll('*').some(el => el.shadowRoot)
```

**Fix:** Pierce shadow root:
```javascript
function queryShadow(selector) {
    const parts = selector.split('>>>');
    let node = document;
    for (const part of parts) {
        if (node.shadowRoot) {
            node = node.shadowRoot.querySelector(part.trim());
        } else {
            node = node.querySelector(part.trim());
        }
    }
    return node;
}
```

## Quick Reference

| Issue | Primary Fix | Fallback |
|-------|-------------|----------|
| Scroll not working | Find scrollable container | Mouse wheel at container center |
| Click no effect | JavaScript click() | CDP mouse events |
| Type clears | Add delay_ms | Use `browser_type_focused` (Input.insertText) |
| Snapshot hangs | Add timeout_s | DOM snapshot fallback |
| Stale content | Wait for selector | Increase wait_until timeout |
| Shadow DOM | Pierce selector | JavaScript traversal |

## References

- [registry.md](registry.md) - Full list of known edge cases
- [scripts/test_case.py](scripts/test_case.py) - Template for testing new cases
- [BROWSER_USE_PATTERNS.md](../../tools/BROWSER_USE_PATTERNS.md) - Implementation patterns from browser-use
