---
name: hive.x-automation
description: Drive X / Twitter via the browser-automation toolchain. Verified flows for posting, replying, deleting, search-and-engage, and the compose composer's Draft.js quirks. Includes the daily-reply and job-market-reply patterns distilled from the backed-up x-daily-replies and x-job-market-replies skills. Verified 2026-04-11.
metadata:
  author: hive
  type: default-skill
  version: "1.0"
  verified: 2026-04-11
  requires_skill: hive.browser-automation
---

# X / Twitter Automation

X uses **Draft.js** (the original Facebook rich-text editor) for the compose text area, which was the original canary for all the rich-text editor quirks the `browser-automation` skill now documents. Most of the site is otherwise stable — `data-testid` attributes have held up for years, the SPA is reasonably honest about what it renders, and shadow DOM is minimal. The hard parts are the composer, rate limiting, and the occasional anti-bot challenge.

**Always activate `browser-automation` first.** This skill assumes you already know about CSS-px coordinates, click-first typing, and `Input.insertText`. The guidance below is X-specific.

## Timing expectations

- `browser_navigate(wait_until="load")` returns in **1.3–1.6 s** on a warm cache.
- After navigation, **`sleep(2–3)`** for SPA hydration before querying selectors.
- Compose modal slide-in: **~1.5 s** after clicking reply / compose.
- First 1–2 characters typed into the compose editor **may be dropped** — see "Draft.js quirks" below.

## Verified selectors (2026-04-11)

| Target | Selector |
|---|---|
| Home nav link | `a[data-testid='AppTabBar_Home_Link']` |
| Explore nav link | `a[data-testid='AppTabBar_Explore_Link']` |
| Notifications | `a[data-testid='AppTabBar_Notifications_Link']` |
| Main search input | `input[data-testid='SearchBox_Search_Input']` |
| Compose text area | `[data-testid='tweetTextarea_0']` (Draft.js contenteditable) |
| Post / Tweet submit button | `[data-testid='tweetButton']` |
| Reply button (on feed / tweet detail) | `[data-testid='reply']` |
| Like button | `[data-testid='like']` |
| Retweet / repost button | `[data-testid='retweet']` |
| Caret (⋯) menu on a post | `[data-testid='caret']` |
| Confirmation sheet confirm button | `[data-testid='confirmationSheetConfirm']` |
| Tweet article wrapper | `article[data-testid='tweet']` |
| Close modal / composer | `[aria-label='Close']` or press `Escape` |

All of these are light-DOM `data-testid` attributes — `wait_for_selector` and `browser_type(selector=...)` work on them directly, no shadow piercing needed.

## Post new tweet flow

```
browser_navigate("https://x.com/home", wait_until="load")
sleep(3)

# Open the compose UI (click the post-new-tweet nav or use shortcut N)
browser_press("n")   # keyboard shortcut — opens compose modal
sleep(1.5)

# Click the textarea to make sure Draft.js is in edit mode
ta_rect = browser_get_rect("[data-testid='tweetTextarea_0']")
browser_click_coordinate(ta_rect.cx, ta_rect.cy)
sleep(0.5)

# Type — browser_type handles Draft.js correctly now via Input.insertText
browser_type("[data-testid='tweetTextarea_0']", tweet_text)
sleep(1.0)  # let Draft.js commit state

# Verify the Post button is enabled — never click blindly, Draft.js sometimes
# doesn't register the input even with a prior click.
state = browser_evaluate("""
  (function(){
    const btn = document.querySelector('[data-testid="tweetButton"]');
    if (!btn) return {found: false};
    return {
      found: true,
      disabled: btn.disabled || btn.getAttribute('aria-disabled') === 'true',
    };
  })();
""")
if state['found'] and not state['disabled']:
    browser_click("[data-testid='tweetButton']")
    sleep(2)
    browser_press("Escape")  # close any leftover modal
```

## Reply to a post flow

The reply flow is the same shape as posting, with a few scroll / find-and-click steps before.

```
browser_navigate("https://x.com/home", wait_until="load")
sleep(3)

# Load content by scrolling — X lazy-loads feed items
browser_scroll(direction="down", amount=2000)
sleep(1.5)

# Find replyable tweets — reply buttons, in visual/feed order
candidates = browser_evaluate("""
  (function(){
    const tweets = document.querySelectorAll('article[data-testid="tweet"]');
    const out = [];
    tweets.forEach((t, i) => {
      const reply = t.querySelector('[data-testid="reply"]');
      if (!reply) return;
      const r = reply.getBoundingClientRect();
      if (r.width <= 0 || r.y < 0 || r.y > window.innerHeight) return;
      const text = (t.textContent || '').slice(0, 120);
      out.push({
        index: i,
        preview: text,
        cx: r.x + r.width/2,
        cy: r.y + r.height/2,
      });
    });
    return out;
  })();
""")

# For each unreplied candidate...
for c in candidates:
    if already_replied(c['preview']):
        continue  # see dedup pattern below

    # Click reply
    browser_click_coordinate(c['cx'], c['cy'])
    sleep(1.5)  # composer slide-in

    # Click the textarea to focus Draft.js
    ta = browser_get_rect("[data-testid='tweetTextarea_0']")
    browser_click_coordinate(ta.cx, ta.cy)
    sleep(0.5)

    # Type the reply
    browser_type("[data-testid='tweetTextarea_0']", reply_text)
    sleep(1.5)   # Draft.js state commit takes a beat

    # Verify button enabled
    state = browser_evaluate("""
      (function(){
        const b = document.querySelector('[data-testid="tweetButton"]');
        return b ? {d: b.disabled || b.getAttribute('aria-disabled') === 'true'} : {d: true};
      })();
    """)
    if state['d']:
        # Recovery: click the textarea again + one extra character toggles React state
        browser_click_coordinate(ta.cx, ta.cy)
        browser_press("End")
        browser_press(" ")
        browser_press("Backspace")
        sleep(0.5)
    else:
        browser_click("[data-testid='tweetButton']")
        sleep(2)
        record_sent(c['preview'], reply_text)  # append to ledger

    # Close the composer (press Escape or click the Close button)
    browser_press("Escape")
    sleep(random.uniform(10, 20))   # human cadence — see rate limits
```

## Search-and-engage flow

For "daily reply to live posts matching query X" — e.g. job-market replies.

```
query = "job market"
url = f"https://x.com/search?q={urllib.parse.quote(query)}&src=typed_query&f=live"
browser_navigate(url, wait_until="load")
sleep(3)
browser_scroll("down", 2000)
sleep(1.5)

# Same replyable-tweets probe as above, then same reply-to-tweet loop
```

## Delete a post flow

```
browser_navigate("https://x.com/<your_username>/with_replies", wait_until="load")
sleep(3)

# Find the target article (by text match or index)
target_caret = browser_evaluate("""
  (function(target_text){
    const tweets = document.querySelectorAll('article[data-testid="tweet"]');
    for (const t of tweets){
      if (!(t.textContent || '').includes(target_text)) continue;
      const caret = t.querySelector('[data-testid="caret"]');
      if (!caret) continue;
      const r = caret.getBoundingClientRect();
      return {cx: r.x + r.width/2, cy: r.y + r.height/2};
    }
    return null;
  })();
""", target_text)

browser_click_coordinate(target_caret['cx'], target_caret['cy'])
sleep(0.8)   # menu animation

# The Delete menuitem doesn't have a stable data-testid — find by text
delete_rect = browser_evaluate("""
  (function(){
    const items = document.querySelectorAll('[role="menuitem"]');
    for (const el of items){
      if ((el.textContent || '').trim() === 'Delete'){
        const r = el.getBoundingClientRect();
        return {cx: r.x + r.width/2, cy: r.y + r.height/2};
      }
    }
    return null;
  })();
""")
browser_click_coordinate(delete_rect['cx'], delete_rect['cy'])
sleep(0.8)

# Confirmation sheet — this one DOES have a stable testid
browser_click("[data-testid='confirmationSheetConfirm']")
sleep(1.5)
```

## Draft.js quirks

X's compose editor is the canonical test case for every rich-text-editor bug the GCU bridge has ever had. What you need to know:

- **Click the textarea first.** Mandatory. Without a native click-sourced focus event, Draft.js's editor state never enters edit mode, and the Post button stays disabled regardless of how much text you type. `browser_type` now does this click automatically.

- **`browser_type` uses CDP `Input.insertText` by default**, which Draft.js accepts cleanly. The older approach — per-character `Input.dispatchKeyEvent` with `delay_ms=20` — *also* works, but insertText is more reliable and faster. Only pass `delay_ms > 0` (which falls back to per-char dispatch) if you're specifically testing the keystroke timing path.

- **First 1–2 characters may be eaten** on the per-char dispatch path (not on insertText). If you see `"estin"` instead of `"testin"`, prepend a throwaway character or use insertText.

- **Verify `tweetButton`'s `disabled` state** before clicking. Draft.js's internal state can disagree with the DOM text — verify framework state via a targeted `browser_evaluate` on `aria-disabled`.

- **If the button stays disabled after typing**, use the recovery dance: click the textarea again, press `End`, press a space, press `Backspace`. This forces React to recompute `hasRealContent` and usually flips the button on.

- **URL previews take a beat to render.** If your tweet ends with a URL, wait 2–3 s after typing so the link-card preview loads before you post — otherwise the tweet publishes without the card.

## Rate limits and safety

| Action | Limit |
|---|---|
| Tweets per hour | ~50 before throttling |
| Replies per session | **5–10 per run**, randomized 10–20 s delays |
| DMs per day | Varies by account age; 50–100 for established accounts |
| Follow/unfollow | <400/day spread over time |
| Like per day | 1000 max; 200–300 is safer |

Signals you're being rate-limited or flagged:
- 429 status in network responses (not always visible to the agent)
- "You are unable to Tweet" banner
- Redirect to `https://x.com/account/access` (anti-bot check)
- Posts appearing to publish but not visible on your profile
- Reply button click opens but composer never receives focus

If any of these appear, **stop the run, screenshot the state, and surface the issue.** Do not retry immediately.

## Deduplication pattern

Every daily loop should maintain a ledger file. Append after each successful reply/post, atomic-write to survive crashes.

```
# data/x_replies_ledger.json
{
  "replies": [
    {
      "tweet_url": "https://x.com/<author>/status/<id>",
      "author": "username",
      "original_preview": "first 100 chars of the tweet",
      "reply_text": "what you sent",
      "timestamp": "2026-04-13T09:30:00Z"
    }
  ]
}
```

Extract the tweet URL via `browser_evaluate`:

```
url = browser_evaluate("""
  (function(article_index){
    const t = document.querySelectorAll('article[data-testid="tweet"]')[article_index];
    if (!t) return null;
    const link = t.querySelector('a[href*="/status/"]');
    return link ? link.href : null;
  })();
""", article_index)
```

Before each reply, check if the URL already has a ledger entry. If yes, skip. This survives across runs and across days.

## Reply style guidelines

These are soft rules derived from the backed-up `x-daily-replies` and `x-job-market-replies` skills — tune per your operator's preference.

**Daily replies (siren_fs persona, dark humorous):**
- 2 sentences MAX
- Dark, humorous, insightful, trendy
- Must feel like a real person with opinions and edge
- Must NOT sound like AI, use corporate speak, or be corny
- Tie to current news/culture when possible
- English only
- Target: 5–8 replies per run
- Skip posts that are purely images/video with no text context
- Prioritize high-engagement accounts
- Skip ads unless genuinely interesting

**Job-market replies (casual slang + prediction-market CTA):**
- 2–3 short sentences max
- Casual slang, alt spellings: "u", "fr", "lmao", "lol"
- Always include a profile-level CTA ("check my profile if u wanna see…")
- Tie the reply to the economic / career angle of the original post
- Vary templates — never identical text across replies
- Max 10 replies per session

## Common pitfalls

- **Typing without clicking first → send button stays disabled.** Draft.js only enters edit mode after a native focus event. `browser_type` handles this automatically now, but if you're using raw CDP calls, click first.

- **First 1–2 chars eaten on per-char dispatch.** Stick with `browser_type` default (uses `Input.insertText`). Only use `delay_ms=20` fallback if you need per-keystroke timing.

- **Clicking Post with Draft.js state disagreeing.** Always verify `[data-testid="tweetButton"]`'s `disabled` / `aria-disabled` before clicking. If disabled, run the recovery dance.

- **Anti-bot challenge mid-run.** X occasionally shows a JavaScript challenge or redirects to `/account/access`. Detect by checking the URL after navigation and the presence of the home nav:
  ```
  challenged = browser_evaluate("""
    (function(){
      return window.location.href.includes('/account/access') ||
             !document.querySelector('a[data-testid="AppTabBar_Home_Link"]');
    })();
  """)
  ```
  If challenged, stop and surface to the operator. Do not try to solve it.

- **Composer modal fails to open on rapid clicks.** X debounces the reply button click. Always `sleep(1.5)` after clicking before trying to query the textarea.

- **Navigation inside the SPA is preferred over full page loads.** Clicking a tweet to open its detail view keeps the compose state; using `browser_navigate` reloads everything and slows the run. Use `browser_click` on internal links when possible.

- **X's `window.innerHeight` changes on compose modal open.** The modal takes over most of the viewport. Don't cache viewport dimensions across a compose open; re-query after the modal slide-in.

- **URL-only tweets post without a link card if you click Post too fast.** Wait 2–3 s after typing a URL before clicking Post so the card preview renders.

## Auth wall detection

Check logged-in state before any action:

```
logged_in = browser_evaluate("""
  (function(){
    return !!document.querySelector('a[data-testid="AppTabBar_Home_Link"]') &&
           !window.location.href.includes('/i/flow/login');
  })();
""")
```

If not logged in, **stop immediately** and surface. Do not attempt to log in via automation.

## See also

- `browser-automation` skill — general CDP/coord/screenshot rules, click-then-type pattern, Input.insertText
- `linkedin-automation` skill — LinkedIn equivalent
