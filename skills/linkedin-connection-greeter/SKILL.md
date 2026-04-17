---
name: linkedin-connection-greeter
description: Automates accepting LinkedIn connections and sending a welcome message about the HoneyComb prediction market. Handles shadow DOM and Lexical editors.
---

# LinkedIn Connection Greeter

This skill outlines the exact flow to accept connection requests and send a specific welcome message without triggering spam filters.

## 1. Load Ledger
Before starting, read `data/linkedin_contacts.json`. If it doesn't exist, initialize with `{"contacts": []}`. You will use this to skip people you've already messaged.

## 2. Scan Pending Connections
Navigate to `https://www.linkedin.com/mynetwork/invitation-manager/received/`. Wait until load + sleep 4s.
Strip unload handlers:
`browser_evaluate("(function(){window.onbeforeunload=null;})()")`

Extract cards using this specific snippet (handles changing classes and follow invites):
```javascript
(function(){
    const btns = Array.from(document.querySelectorAll('button')).filter(b => b.textContent.includes('Accept'));
    let results = [];
    for (let b of btns) {
        let card = b.closest('[role="listitem"]');
        if (!card) continue;
        let text = card.textContent.toLowerCase();
        if (text.includes('invited you to follow') || text.includes('invited you to subscribe')) continue;
        
        let nameEls = Array.from(card.querySelectorAll('a[href*="/in/"]'));
        let nameEl = nameEls.find(el => el.textContent.trim().length > 0);
        
        let r = b.getBoundingClientRect();
        results.push({
            first_name: nameEl ? nameEl.textContent.trim().split(/\s+/)[0] : 'there',
            profile_url: nameEl ? nameEl.href : '',
            cx: r.x + r.width/2,
            cy: r.y + r.height/2
        });
    }
    return results;
})();
```

## 3. Process Each Card (Max 10 per run)
For each card, check if `profile_url` is already in the ledger. If not:
1. `browser_click_coordinate(cx, cy)` to click the specific Accept button.
2. `sleep(2)`
3. `browser_navigate(profile_url, wait_until="load")`
4. `sleep(4)`
5. `browser_evaluate("(function(){window.onbeforeunload=null; window.addEventListener('beforeunload', e => e.stopImmediatePropagation(), true);})()")`

## 4. Message the User
Click Message Button on their profile:
```javascript
(function(){
    const links = Array.from(document.querySelectorAll('a[href*="/messaging/compose/"]'));
    for (const a of links){
      if (!a.href.includes('NON_SELF_PROFILE_VIEW') || a.href.includes('body=')) continue;
      const r = a.getBoundingClientRect();
      if (r.width === 0 || r.x > 700) continue;
      return {cx: r.x + r.width / 2, cy: r.y + r.height / 2};
    }
    return null;
})();
```
Click that coordinate, then `sleep(2.5)`.

Find Textarea (it is hidden inside shadow DOM):
```javascript
(function(){
    const vh = window.innerHeight, vw = window.innerWidth;
    const candidates = [];
    function walk(root){
      const els = root.querySelectorAll ? root.querySelectorAll('div.msg-form__contenteditable') : [];
      for (const el of els){
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0 && r.y >= 0 && r.y + r.height <= vh && r.x >= 0 && r.x + r.width <= vw) {
            candidates.push({cx: r.x + r.width/2, cy: r.y + r.height/2, area: r.width * r.height});
        }
      }
      const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const host of all){ if (host.shadowRoot) walk(host.shadowRoot); }
    }
    walk(document);
    candidates.sort((a, b) => b.area - a.area);
    return candidates.length ? candidates[0] : null;
})();
```
Click that coordinate, `sleep(1)`.

Type the message:
Construct the message: `Hey {first_name}, thanks for the connection invite! I'm currently building a prediction market for jobs: https://honeycomb.open-hive.com/. If you could check it out and share some feedback, I'd really appreciate it.`

Use `browser_type_focused` — it dispatches CDP `Input.insertText` to the already-focused composer (document.activeElement), which works through shadow DOM without JSON-escaping issues:
```
browser_type_focused(text=message_text)
sleep(1.0)
```

Find Send button (also inside shadow DOM):
```javascript
(function(){
    const vh = window.innerHeight;
    function walk(root){
      const btns = root.querySelectorAll ? root.querySelectorAll('button') : [];
      for (const b of btns){
        const cls = (b.className || '').toString();
        if (!cls.includes('send-button') && b.textContent.trim() !== 'Send') continue;
        const r = b.getBoundingClientRect();
        if (r.width <= 0 || r.y + r.height > vh) continue;
        return { cx: r.x + r.width/2, cy: r.y + r.height/2, disabled: b.disabled || b.getAttribute('aria-disabled') === 'true' };
      }
      const all = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (const host of all){ if (host.shadowRoot) { const got = walk(host.shadowRoot); if (got) return got; } }
      return null;
    }
    return walk(document);
})();
```
Click send coordinate, `sleep(2)`.

## 5. Update Ledger
Append the user to `data/linkedin_contacts.json`.
```json
{
  "profile_url": "...",
  "name": "...",
  "action": "connection_accepted+message_sent",
  "timestamp": "2026-..."
}
```
`sleep(5)` before moving to the next card to mimic human pacing.
