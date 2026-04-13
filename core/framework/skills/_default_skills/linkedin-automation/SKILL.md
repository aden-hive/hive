---
name: hive.linkedin-automation
description: Drive LinkedIn via the browser-automation toolchain. Verified flows for profile messaging, connection-request acceptance, feed composition, and search. Includes every site-specific quirk we've hit (Trusted Types CSP, #interop-outlet shadow root, Lexical composer, beforeunload draft dialog, rate limits). Verified against logged-in production 2026-04-11.
metadata:
  author: hive
  type: default-skill
  version: "1.0"
  verified: 2026-04-11
  requires_skill: hive.browser-automation
---

# LinkedIn Automation

LinkedIn is the hardest mainstream site to automate because it combines **shadow DOM** (`#interop-outlet` for messaging), **strict Trusted Types CSP** (silently drops `innerHTML`), **heavy React reconciliation** (injected nodes get stripped on re-render), **native `beforeunload` draft dialogs** (hang the bridge), and **aggressive spam filters**. Every one of those has bit us at least once. This skill documents what actually works.

**Always activate `browser-automation` first.** This skill assumes you already know about CSS-px coordinates, `browser_type`'s click-first behavior, and `browser_shadow_query`. The guidance below is LinkedIn-specific; general browser rules are there.

## Timing expectations

- `browser_navigate(wait_until="load", timeout_ms=20000)` — LinkedIn takes **4–5 seconds** to load the feed cold. Default 30s timeout is fine; use 20s as a floor.
- After navigation, **always `sleep(3)`** to let React hydrate the profile/feed chrome before querying selectors. Without the sleep `wait_for_selector` will flake on elements that exist moments later.
- Composer modal slide-in takes **~2 seconds** after you click the Message button.

## Verified selectors (2026-04-11)

| Target | Selector | Notes |
|---|---|---|
| Global search input | `input[data-testid='typeahead-input']` | Light DOM, straightforward |
| Own profile link | `a[href*='linkedin.com/in/']` | Top nav; filter to the one near top-left |
| Profile **Message** action | `a[href*='/messaging/compose/']` filtered by `NON_SELF_PROFILE_VIEW` AND no `body=` param AND `x < 700` | **Is an `<a>`**, not a `<button>`. Multiple match; filter carefully. |
| Modal composer textarea | `div.msg-form__contenteditable` (inside `#interop-outlet` shadow) | **Multiple instances exist** — pick largest-area **in-viewport** one. |
| Modal Send button | `button.msg-form__send-button` (inside `#interop-outlet` shadow) | Same multi-instance trap — filter by `y + height <= innerHeight`. |
| Invitation manager | navigate to `https://www.linkedin.com/mynetwork/invitation-manager/received/` | Direct URL is faster than nav-link clicking |
| Pending connection card | `.invitation-card, .invitations-card, [data-test-incoming-invitation-card]` | Filter out "invited you to follow" / "subscribe" cards |
| Accept button | `button[aria-label*="Accept"]` within the card scope | Per-card scoping is critical — there are many Accept buttons on the page |

LinkedIn changes class names aggressively. If a class-based selector breaks, fall back to **`browser_screenshot` → visual identification → `browser_coords` → `browser_click_coordinate`**. The screenshot + coord path works regardless of class-name churn and regardless of shadow DOM.

## Profile Message flow (verified end-to-end 2026-04-11)

```
# 1. Load the profile
browser_navigate("https://www.linkedin.com/in/<username>/", wait_until="load", timeout_ms=20000)
sleep(4)

# 2. Strip onbeforeunload before any state-mutating work — prevents draft-dialog deadlock later
browser_evaluate("""
  (function(){
    window.onbeforeunload = null;
    window.addEventListener('beforeunload', e => e.stopImmediatePropagation(), true);
  })();
""")

# 3. Find the profile Message link (NOT a button, and multiple exist)
msg_btn = browser_evaluate("""
  (function(){
    const links = Array.from(document.querySelectorAll('a[href*="/messaging/compose/"]'));
    for (const a of links){
      const href = a.href || '';
      if (!href.includes('NON_SELF_PROFILE_VIEW')) continue;
      if (href.includes('body=')) continue;            // reject Premium upsell
      const r = a.getBoundingClientRect();
      if (r.width === 0 || r.x > 700) continue;        // reject sidebar / "More profiles for you"
      return {cx: r.x + r.width / 2, cy: r.y + r.height / 2};
    }
    return null;
  })();
""")
browser_click_coordinate(msg_btn['cx'], msg_btn['cy'])
sleep(2.5)  # composer modal slide-in

# 4. Find the modal composer textarea (pick biggest in-viewport; reject pinned chat bar)
textarea = browser_evaluate("""
  (function(){
    const vh = window.innerHeight, vw = window.innerWidth;
    const candidates = [];
    function walk(root){
      const els = root.querySelectorAll ?
        root.querySelectorAll('div.msg-form__contenteditable') : [];
      for (const el of els){
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        if (r.y < 0 || r.y + r.height > vh) continue;  // reject pinned bar (below viewport)
        if (r.x < 0 || r.x + r.width > vw) continue;
        candidates.push({cx: r.x + r.width/2, cy: r.y + r.height/2, area: r.width * r.height});
      }
      const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const host of all){ if (host.shadowRoot) walk(host.shadowRoot); }
    }
    walk(document);
    if (!candidates.length) return null;
    candidates.sort((a, b) => b.area - a.area);
    return candidates[0];
  })();
""")

# 5. Click to focus the modal composer (click-first is mandatory for Lexical)
browser_click_coordinate(textarea['cx'], textarea['cy'])
sleep(0.6)

# 6. Insert text via CDP Input.insertText (browser_type does this by default now).
#    Per-char keyDown fails on Lexical composers — the keys dispatch but
#    the editor never turns them into text.
browser_type(<appropriate-selector-or-skip-selector-and-use-bridge-insertText>, text)

# 7. Find the modal Send button (filter by in-viewport, reject pinned bar)
send = browser_evaluate("""
  (function(){
    const vh = window.innerHeight;
    function walk(root){
      const btns = root.querySelectorAll ? root.querySelectorAll('button') : [];
      for (const b of btns){
        const cls = (b.className || '').toString();
        const txt = (b.textContent || '').trim();
        if (!cls.includes('send-button') && txt !== 'Send') continue;
        const r = b.getBoundingClientRect();
        if (r.width <= 0 || r.y + r.height > vh) continue;
        return {
          cx: r.x + r.width/2, cy: r.y + r.height/2,
          disabled: b.disabled || b.getAttribute('aria-disabled') === 'true',
        };
      }
      const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const host of all){
        if (host.shadowRoot){
          const got = walk(host.shadowRoot);
          if (got) return got;
        }
      }
      return null;
    }
    return walk(document);
  })();
""")

# 8. ONLY click Send if it's enabled — if disabled, the editor didn't register the input.
#    Don't click blindly; the framework state is the source of truth, not the DOM text.
if not send['disabled']:
    browser_click_coordinate(send['cx'], send['cy'])
    sleep(2.5)  # wait for send + bubble render
```

**Verify post-send**: the composer textarea should now be empty (`innerText === ''`) and `.msg-s-event-listitem__message-bubble` count should have grown by 1. Walk the shadow tree via `browser_evaluate` to check.

## Connection request acceptance flow

Daily outbound pattern — accept pending connection requests and send a templated welcome message.

```
browser_navigate("https://www.linkedin.com/mynetwork/invitation-manager/received/",
                 wait_until="load", timeout_ms=20000)
sleep(4)
browser_evaluate("(function(){window.onbeforeunload=null;})()")

# Scan pending connection cards — FILTER OUT follow/subscribe invitations
cards = browser_evaluate("""
  (function(){
    const out = [];
    const cards = document.querySelectorAll('[data-test-incoming-invitation-card], .invitation-card');
    for (const c of cards){
      const text = (c.textContent || '').toLowerCase();
      if (text.includes('invited you to follow')) continue;
      if (text.includes('invited you to subscribe')) continue;
      const nameEl = c.querySelector('a[href*="/in/"], strong');
      const name = nameEl ? nameEl.textContent.trim().split(/\\s+/)[0] : '';
      const accept = c.querySelector('button[aria-label*="Accept"]');
      if (!accept) continue;
      const r = accept.getBoundingClientRect();
      out.push({
        first_name: name,
        cx: r.x + r.width/2, cy: r.y + r.height/2,
      });
      if (out.length >= 25) break;   // strict daily cap — see rate limits below
    }
    return out;
  })();
""")

# Process cards one at a time with human-like cadence
for card in cards[:25]:
    browser_click_coordinate(card['cx'], card['cy'])   # click Accept
    sleep(2)
    # After accepting, a "Message" button appears on the card — navigate to
    # the profile and run the profile Message flow above, personalized by first_name.
    # OR: if the "Message" button is inline on the card, click it directly and
    # use the shadow-root composer flow.
    sleep(random.uniform(5, 10))  # human-like delay BETWEEN targets
```

**Don't do 25 back-to-back sends with zero delay.** LinkedIn's spam filter catches this. 5–10 second randomized sleeps between sends, hard cap at 25 per 24h window.

## Feed post composer flow

```
browser_navigate("https://www.linkedin.com/feed/", wait_until="load", timeout_ms=20000)
sleep(4)
browser_evaluate("(function(){window.onbeforeunload=null;})()")

# Click the "Start a post" trigger
start_trigger = browser_get_rect("button.share-box-feed-entry__trigger, [aria-label*='Start a post']")
browser_click_coordinate(start_trigger.cx, start_trigger.cy)
sleep(1.5)  # modal slide-in

# Find the post editor inside the modal (also contenteditable, may not be in shadow)
editor = browser_get_rect("div[contenteditable=true][aria-placeholder*='talk about']")
browser_click_coordinate(editor.cx, editor.cy)
sleep(0.5)
browser_type("div[contenteditable=true][aria-placeholder*='talk about']", post_text)
sleep(1.0)

# Verify Post button enabled before clicking
state = browser_evaluate("""
  (function(){
    const btn = document.querySelector('button.share-actions__primary-action');
    if (!btn) return {found: false};
    return {
      found: true,
      disabled: btn.disabled || btn.getAttribute('aria-disabled') === 'true',
    };
  })();
""")
if state['found'] and not state['disabled']:
    browser_click("button.share-actions__primary-action")
```

## Rate limits and safety

LinkedIn's abuse detection is aggressive. Respect these limits:

| Action | Limit |
|---|---|
| Outbound messages to non-connections | **Do not attempt** — will get you warned or restricted |
| Outbound messages to new 1st-degree connections | **25/day max**, 5–10s randomized delays |
| Connection request sends | **100/week max**, spread across days, warm intros preferred |
| Profile views | Several hundred/day is usually fine but varies by account age |
| Post publications | 1–3/day, no URL-only posts |
| Feed reactions | Dozens/day is fine; vary your activity mix |

Signals you're being throttled:
- "Message failed to send" with no error detail
- Redirect to `https://www.linkedin.com/checkpoint/challenge/...`
- Profile views showing stale data
- Connection requests auto-withdrawn after a few hours

If any of those show up, **stop the run, screenshot the state, and surface the issue to the human operator.** Do not retry.

## Common pitfalls

- **`innerHTML` injection is silently dropped** — LinkedIn's Trusted Types CSP discards any `innerHTML = "<...>"` from injected scripts, no console error. Always use `createElement` + `appendChild` + `setAttribute` for DOM injection. `textContent`, `style.cssText`, and `.value` assignments are fine.
- **Per-char keyDown on the message composer produces empty text** — Lexical intercepts `beforeinput` and drops raw keys. Use `browser_type` (which now routes through CDP `Input.insertText`), or call `Input.insertText` directly via the bridge on the focused shadow element.
- **`browser_type(selector=...)` can't see the message composer** — it's inside `#interop-outlet` shadow. `document.querySelector('div.msg-form__contenteditable')` returns nothing. Use the shadow-walk + click-to-focus pattern above.
- **Multiple Send buttons on the page** — the pinned bottom-right messaging bar has its own `msg-form__send-button` that's usually below `innerHeight`. Filter by in-viewport before clicking.
- **`window.onbeforeunload` hangs navigation/close** — after typing in a composer, any `browser_navigate` or `close_tab` can pop a native "unsent message, leave?" confirm dialog that deadlocks the bridge. Always strip `onbeforeunload` before any navigation, and wrap composer flows in a `try/finally` that runs the cleanup block:

```
# Cleanup on exit — run even if the flow crashed mid-type.
browser_evaluate("""
  (function(){
    window.onbeforeunload = null;
    const h = document.getElementById('__hive_hl');
    if (h) { try { h.__hiveStop && h.__hiveStop(); } catch(_){}; h.remove(); }
  })();
""")
```

- **SPA reconciliation strips injected overlays** — LinkedIn's React reconciler removes foreign children of `documentElement` on re-render. The framework highlight overlay survives (re-mount observer + bounded retries), but test overlays injected via raw `browser_evaluate` may not. If you need a stable test overlay, append it to `document.documentElement` AND wrap in a `MutationObserver` that re-appends on removal, capped at ~20 retries.
- **Profile page chrome is not in the AX snapshot** — `browser_snapshot` on a profile misses a lot of the structured layout. Use `browser_screenshot` to orient; use specific selectors or the shadow-walk pattern for actions.
- **Name parsing from a connection card is fragile** — the card layout changes every few months. Prefer `.textContent.split(/\s+/)[0]` on the first link inside the card rather than relying on a class like `.invitation-card-name`.

## Auth wall detection

If you see a "Log in" / "Join LinkedIn" prompt instead of the logged-in feed, **stop immediately** and surface the issue. Do NOT attempt to log in via automation — LinkedIn's bot detection will flag the account.

Check via:
```
is_logged_in = browser_evaluate("""
  (function(){
    return !!document.querySelector('nav.global-nav') ||
           !!document.querySelector('[data-test-global-nav-me]');
  })();
""")
```

## Deduplication pattern

For any daily loop (connection acceptance, profile visits, DMs), maintain a ledger file:

```
# data/linkedin_contacts.json
{
  "contacts": [
    {
      "profile_url": "https://www.linkedin.com/in/username/",
      "name": "First Last",
      "action": "connection_accepted+message_sent",
      "timestamp": "2026-04-13T09:30:00Z",
      "message_preview": "first 50 chars of message sent"
    }
  ]
}
```

Before any action, check if the profile URL already has a recent entry for the same action. Skip if yes. Atomic-write the ledger after each success so crash-resume works.

## See also

- `browser-automation` skill — general CDP/coord/screenshot rules, the click-then-type pattern, shadow-DOM strategy
- `x-automation` skill — X/Twitter equivalent
