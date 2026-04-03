# Browser Edge Case Registry

Curated list of known browser automation edge cases with symptoms, causes, and fixes.

---

## Scroll Issues

### #1: LinkedIn Nested Scroll Container

| Attribute | Value |
|-----------|-------|
| **Site** | LinkedIn (linkedin.com/feed) |
| **Symptom** | `browser_scroll()` returns `{ok: true}` but page doesn't move |
| **Root Cause** | Content is in a nested scrollable div (`overflow: scroll`), not the main window |
| **Detection** | `document.querySelectorAll('*')` with `overflow: scroll/auto` has large candidates |
| **Fix** | Find largest scrollable container, dispatch mouse wheel at its center coordinates |
| **Code** | `bridge.py:808-981` - smart scroll with container detection |
| **Verified** | 2026-04-02 |

### #2: Twitter/X Lazy Loading

| Attribute | Value |
|-----------|-------|
| **Site** | Twitter/X (x.com) |
| **Symptom** | Infinite scroll doesn't load new content |
| **Root Cause** | Lazy loading requires content to be visible before loading more |
| **Detection** | Scroll position at bottom but no new `[data-testid="tweet"]` elements |
| **Fix** | Add `wait_for_selector` between scroll calls with 1s delay |
| **Code** | Test file: `tests/test_x_page_load_repro.py` |
| **Verified** | - |

### #3: Modal/Dialog Scroll Container

| Attribute | Value |
|-----------|-------|
| **Site** | Any site with modal dialogs |
| **Symptom** | Scroll scrolls background page, not modal content |
| **Root Cause** | Modal has its own scroll container with `overflow: scroll` |
| **Detection** | Visible element with `position: fixed` and scrollable content |
| **Fix** | Find visible modal container (highest z-index scrollable), scroll that |
| **Code** | - |
| **Verified** | - |

---

## Click Issues

### #4: Element Covered by Overlay

| Attribute | Value |
|-----------|-------|
| **Site** | SPAs, sites with loading overlays |
| **Symptom** | Click succeeds but no action triggered |
| **Root Cause** | Element is covered by transparent overlay, tooltip, or iframe |
| **Detection** | `document.elementFromPoint(x, y) !== target` |
| **Fix** | Wait for overlay to disappear, or use JavaScript `element.click()` |
| **Code** | `bridge.py:394-591` - JavaScript click as primary |
| **Verified** | - |

### #5: React Synthetic Events

| Attribute | Value |
|-----------|-------|
| **Site** | React applications |
| **Symptom** | CDP click doesn't trigger React handler |
| **Root Cause** | React uses synthetic events that don't respond to CDP events |
| **Detection** | Site uses React (check for `__reactFiber$` or `data-reactroot`) |
| **Fix** | Use JavaScript `element.click()` as primary method |
| **Code** | `bridge.py:394-591` - JavaScript-first click |
| **Verified** | - |

### #6: Shadow DOM Elements

| Attribute | Value |
|-----------|-------|
| **Site** | Components using Shadow DOM, Lit elements |
| **Symptom** | `querySelector` can't find element |
| **Root Cause** | Element is inside a shadow root, not main DOM tree |
| **Detection** | `element.shadowRoot !== null` on parent elements |
| **Fix** | Use piercing selector (`host >>> target`) or traverse shadow roots |
| **Code** | See SKILL.md P6 pattern |
| **Verified** | - |

---

## Input Issues

### #7: ContentEditable / Rich Text Editors

| Attribute | Value |
|-----------|-------|
| **Site** | Rich text editors (Notion, Slack web, etc.) |
| **Symptom** | `browser_type()` doesn't insert text |
| **Root Cause** | Element is `contenteditable`, not an `<input>` or `<textarea>` |
| **Detection** | `element.contentEditable === 'true'` |
| **Fix** | Focus via JavaScript, use `execCommand('insertText')` or `Input.dispatchKeyEvent` |
| **Code** | `bridge.py:616-694` - contentEditable handling |
| **Verified** | - |

### #8: Autocomplete Field Clearing

| Attribute | Value |
|-----------|-------|
| **Site** | Search fields with autocomplete, address forms |
| **Symptom** | Typed text gets cleared immediately |
| **Root Cause** | Field expects realistic keystroke timing for autocomplete |
| **Detection** | Field has autocomplete listeners or dropdown appears |
| **Fix** | Add `delay_ms=50` between keystrokes |
| **Code** | `bridge.py:type()` - delay_ms parameter |
| **Verified** | - |

### #9: Custom Date Pickers

| Attribute | Value |
|-----------|-------|
| **Site** | Forms with custom date widgets |
| **Symptom** | Can't type date into date field |
| **Root Cause** | Custom widget intercepts and blocks keyboard input |
| **Detection** | Typing doesn't change field value |
| **Fix** | Click calendar widget icon, select date from dropdown |
| **Code** | - |
| **Verified** | - |

---

## Snapshot Issues

### #10: LinkedIn Huge DOM Tree

| Attribute | Value |
|-----------|-------|
| **Site** | LinkedIn, Facebook, Twitter feeds |
| **Symptom** | `browser_snapshot()` hangs forever |
| **Root Cause** | 10k+ DOM nodes, accessibility tree has 50k+ nodes |
| **Detection** | `document.querySelectorAll('*').length > 5000` |
| **Fix** | Add timeout (10s default), truncate tree at 2000 nodes |
| **Code** | `bridge.py:1005-1050` - timeout_s param, max_nodes limit |
| **Verified** | 2026-04-02 |

### #11: SPA Hydration Delay

| Attribute | Value |
|-----------|-------|
| **Site** | React/Vue/Angular SPAs |
| **Symptom** | Snapshot shows old content after navigation |
| **Root Cause** | Client-side hydration hasn't completed when snapshot runs |
| **Detection** | `document.readyState === 'complete'` but content missing |
| **Fix** | Wait for specific selector after navigation |
| **Code** | Test file: `tests/test_x_page_load_repro.py` |
| **Verified** | - |

### #12: iframe Content Missing

| Attribute | Value |
|-----------|-------|
| **Site** | Sites with embedded content |
| **Symptom** | Snapshot missing iframe content |
| **Root Cause** | Accessibility tree doesn't include iframe content |
| **Detection** | `document.querySelectorAll('iframe')` has results |
| **Fix** | Use `DOM.getFrameOwner` + separate snapshot for each iframe |
| **Code** | - |
| **Verified** | - |

---

## Navigation Issues

### #13: SPA Navigation Events

| Attribute | Value |
|-----------|-------|
| **Site** | React Router, Vue Router SPAs |
| **Symptom** | `wait_until="load"` fires before content ready |
| **Root Cause** | SPA uses client-side routing, no full page load |
| **Detection** | URL changes but `load` event already fired |
| **Fix** | Use `wait_until="networkidle"` or `wait_for_selector` |
| **Code** | `bridge.py:navigate()` - wait_until options |
| **Verified** | - |

### #14: Cross-Origin Redirects

| Attribute | Value |
|-----------|-------|
| **Site** | OAuth flows, SSO logins |
| **Symptom** | Navigation fails during redirect |
| **Root Cause** | Cross-origin security prevents CDP tracking |
| **Detection** | URL changes to different domain |
| **Fix** | Use `wait_for_url` with pattern matching instead of exact URL |
| **Code** | - |
| **Verified** | - |

---

## How to Add New Edge Cases

1. **Reproduce** the issue with minimal test case
2. **Document** using the template below
3. **Implement** fix with multi-layer fallback
4. **Verify** against both problematic and simple sites
5. **Submit** by appending to this file

### Template

```markdown
### #N: [Short Title]

| Attribute | Value |
|-----------|-------|
| **Site** | [URL or site type] |
| **Symptom** | [What the user observes] |
| **Root Cause** | [Technical explanation] |
| **Detection** | [JavaScript to detect this case] |
| **Fix** | [Solution approach] |
| **Code** | [File:line reference if implemented] |
| **Verified** | [Date or "pending"] |
```

---

## Statistics

| Category | Count |
|----------|-------|
| Scroll Issues | 3 |
| Click Issues | 3 |
| Input Issues | 3 |
| Snapshot Issues | 3 |
| Navigation Issues | 2 |
| **Total** | **14** |

Last updated: 2026-04-02
