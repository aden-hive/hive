---
name: hive.linkedin-automation
description: Read before automating LinkedIn with browser_* tools. LinkedIn combines shadow DOM (#interop-outlet), strict Trusted Types CSP that silently drops innerHTML, Lexical composer, native beforeunload dialogs that hang the bridge, and aggressive spam filters — each has bitten us at least once. Verified flows for profile messaging, connection-request acceptance, feed composition, and search. Requires hive.browser-automation. Verified against logged-in production 2026-04-11.
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

# 6. Insert text via browser_type WITHOUT a selector. This dispatches
#    CDP Input.insertText to document.activeElement — the same underlying
#    mechanism as execCommand('insertText') but with no JSON escaping,
#    no browser_evaluate round trip, and built-in retry. The click in
#    step 5 already focused Lexical, so insertText lands in the editor
#    regardless of the shadow wrapping around #interop-outlet.
#
#    Do NOT pass a selector here. Selector-based browser_type cannot see
#    past the #interop-outlet shadow root. No-selector mode sidesteps
#    that entirely by routing to activeElement.
browser_type(text=message_text)   # no selector — targets document.activeElement
sleep(1.0)   # let Lexical commit state + enable Send button

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

# 8. ONLY click Send if it's enabled — if disabled, the insertText
#    didn't land. DO NOT retry with a different tool; the fix is
#    always: re-click the composer rect, re-run browser_type(text=...),
#    re-check. The Send button's `disabled` state IS the ground truth —
#    if Lexical registered your text, it enables the button. If it's
#    still disabled, your text did not reach the editor, regardless
#    of what any tool call claims.
if send['disabled']:
    # The editor didn't receive your text. Do NOT click Send. Do NOT
    # fall back to browser_type with a selector (see anti-pattern in
    # Common Pitfalls — selector-based type can't reach the shadow-DOM
    # composer). Instead: re-click the textarea rect from step 4, wait
    # a beat, re-run browser_type(text=message_text) (no selector) from
    # step 6. If that still fails after 2 retries, bail and surface —
    # the modal may have been reclaimed by a stale state or auth wall.
    raise Exception("Send button disabled after insertText — editor did not receive input")

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

## Posting WITH an image attached

**Do NOT click the "Add media" / image icon inside the feed post composer to pick a file.** LinkedIn renders a styled button that opens Chrome's native OS file picker when clicked, and that dialog is unreachable via CDP — the automation will hang on an invisible modal. Use `browser_upload` directly against the hidden `<input type='file'>`:

```python
# After the post modal is open and the editor has text:
# (A) First, click "Add media" to surface the file input
#     (clicking THIS button reveals the input but does NOT itself open
#     the OS picker on current LinkedIn — the picker only opens if
#     you click the inner "Choose from your device" entry).
media_btn = browser_get_rect("button[aria-label*='image'], button[aria-label*='photo']")
browser_click_coordinate(media_btn.cx, media_btn.cy)
sleep(0.8)

# (B) Enumerate file inputs to find the right one
inputs = browser_evaluate("""
  (function(){
    return Array.from(document.querySelectorAll('input[type="file"]'))
      .map((el, i) => ({
        idx: i,
        accept: el.accept || '',
        name: el.name || '',
      }));
  })();
""")
# Expect to see one with accept='image/*' or accept containing 'image/jpeg'

# (C) Set the file programmatically — no dialog
browser_upload(
    selector="input[type='file'][accept*='image']",
    file_paths=["/absolute/path/to/logo.png"],
)
sleep(3)  # LinkedIn shows an upload-progress bar + preview

# (D) Verify the image preview rendered before clicking Post
preview_ok = browser_evaluate("""
  (function(){
    // LinkedIn shows the preview as an <img> inside
    // .share-creation-state__image-preview or similar.
    return !!document.querySelector(
      '.share-creation-state__preview img, .image-preview-container img'
    );
  })();
""")
if not preview_ok:
    raise Exception("LinkedIn image upload did not render — do NOT click Post")

# (E) Now click Post as usual
browser_click("button.share-actions__primary-action")
sleep(4)  # media post takes longer to commit than text-only
```

If the image isn't already on disk, write it first with `write_file(absolute_path, bytes)`. `browser_upload` only accepts absolute paths.

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
- **Do NOT pass a selector to `browser_type` on the message composer — call it with NO selector (`browser_type(text=...)`).** The Lexical contenteditable lives inside the `#interop-outlet` shadow root which `document.querySelector` (what the selector-based path uses under the hood) cannot see. Attempts to work around this with `browser_shadow_query` fail because selector-based `browser_type` doesn't support the `>>>` shadow-pierce syntax. The reliable insert path is: (1) `browser_click_coordinate` on the composer rect — the response's `focused_element` confirms Lexical received focus → (2) `browser_type(text=message_text)` with NO selector — CDP `Input.insertText` dispatches to `document.activeElement` regardless of shadow wrapping. The old `browser_evaluate` + `document.execCommand('insertText', ...)` pattern worked but had JSON-escaping pitfalls and cost ~200 chars of JS per send; `browser_type(text=...)` is the same mechanism with built-in retry.
- **Per-char keyDown on the message composer produces empty text** — Lexical intercepts `beforeinput` and drops raw keys. Use `browser_type(text=..., use_insert_text=True)` with NO selector after click-coordinate focused the composer. The CDP `Input.insertText` method commits as if IME fired, which Lexical accepts cleanly. Do NOT pass a selector; selector-based `browser_type` can't see past `#interop-outlet`.
- **ANTI-PATTERN: "inject a dummy `<div id='dummy-target'>` and pass it as the `selector` arg to `browser_type`".** This looks tempting but fails compoundingly: `browser_type` clicks the **dummy div's** rect (not the editor's), the click lands on the Lexical wrapper's non-editable chrome, the contenteditable never receives focus, and `Input.insertText` fires against nothing. The bridge will still return `{"ok": true, "action": "type", "length": N}` because it has no way to verify the text actually landed. Symptom: Send button stays `disabled: true` forever. Fix: `browser_click_coordinate` on the real composer rect, then `browser_type(text=message_text)` with NO selector — CDP `Input.insertText` dispatches to `document.activeElement`. (See `session_20260414_114820_08bd3c4d` for the failed dummy-div attempt.)
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
