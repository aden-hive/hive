---
name: hive.x-automation
description: Read before automating X / Twitter with browser_* tools. Verified flows for post, reply, delete, search-and-engage, plus the Draft.js compose quirks that silently disable the send button. Includes the daily-reply and job-market-reply playbooks. Requires hive.browser-automation for the underlying screenshot + coordinate workflow. Verified 2026-04-11.
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

## Posting a tweet WITH an image

**Critical: NEVER click the photo button.** On `x.com/compose/post` the media button is a styled `<button>` that triggers Chrome's native OS file picker when clicked — that dialog is unreachable via CDP and will wedge the automation. Instead, set the file directly on the hidden `<input type='file'>` element using `browser_upload`:

```python
# 1. Open the compose modal as usual
browser_press("n")
sleep(1.5)
browser_click_coordinate(ta_rect.cx, ta_rect.cy)
sleep(0.5)
browser_type("[data-testid='tweetTextarea_0']", tweet_text)

# 2. Find the hidden file input X uses for media uploads.
#    X's input is marked with data-testid='fileInput' and accepts
#    image/*,video/*. It's hidden (display:none) but still mounted.
inputs = browser_evaluate("""
  (function(){
    return Array.from(document.querySelectorAll('input[type="file"]'))
      .map(el => ({
        testid: el.getAttribute('data-testid') || '',
        accept: el.accept || '',
        multiple: el.multiple,
      }));
  })();
""")
# Expect to see: [{testid: 'fileInput', accept: 'image/jpeg,...', multiple: true}]

# 3. Set the file WITHOUT opening any dialog
browser_upload(
    selector="input[data-testid='fileInput']",
    file_paths=["/absolute/path/to/photo.png"],
)
sleep(2)  # X takes ~1-2s to show the preview thumbnail

# 4. Verify the preview rendered before posting — if not, the upload
#    didn't land and Post button will fail.
preview = browser_evaluate("""
  (function(){
    // X renders uploaded media as an <img> with data-testid='attachments'
    // (or similar) inside the composer.
    const att = document.querySelector('[data-testid="attachments"] img');
    return { hasPreview: !!att };
  })();
""")
if not preview['hasPreview']:
    raise Exception("Upload didn't render in composer — do NOT click Post")

# 5. Now click Post as usual
browser_click("[data-testid='tweetButton']")
sleep(3)  # media upload + post takes longer than text-only
browser_press("Escape")
```

If you don't already have the image file on disk, write it first: `write_file("/tmp/x_upload.png", base64_bytes)` or copy from a known location. `browser_upload` requires an absolute file path — relative paths and `~` expansion are not supported.

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
        # Mark the task done in progress.db — see hive.colony-progress-tracker

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

Dedup is handled by the colony progress queue, not a separate JSON file. The queen enqueues one row in the `tasks` table per reply target (keyed by tweet URL); workers claim, reply, and mark done. Already-`done` rows are skipped on the next claim — that's your crash-resume and cross-day dedup, for free. See `hive.colony-progress-tracker` for the full claim/update protocol.

Extract the tweet URL via `browser_evaluate` so the queen can use it as the task key:

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

If you need to check whether a given tweet URL has already been replied to in a prior run (e.g., scanning live search results before enqueuing), query the queue directly:

```bash
sqlite3 "<db_path>" "SELECT status FROM tasks WHERE payload LIKE '%\"tweet_url\":\"<url>\"%';"
```

Empty → not yet enqueued, safe to add. Otherwise honor the existing row's status.

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
