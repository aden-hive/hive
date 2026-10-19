---
name: hive.telegram-notifications-setup
description: Set up a Telegram notification channel (Sentinel) for a colony by driving the browser — create a bot via @BotFather in Telegram Web, store its token, detect the chat to notify, and turn Sentinel on so the colony can ping the user on Telegram and accept replies. Use when the user asks to "set up Telegram notifications", "get pinged on Telegram", "connect Telegram for alerts", "set up Sentinel on Telegram", or clicks the in-app "Set this up with the agent" button on the Telegram step. Requires hive.browser-automation.
metadata:
  author: hive
  type: default-skill
  version: "1.0"
  requires_skill: hive.browser-automation
---

# Telegram Notifications Setup (Sentinel)

Sentinel pings the user on Telegram when a colony stalls and lets them reply to
keep it going. It needs one thing: a **Telegram bot token** (`123456:ABC-…`),
created via @BotFather and stored under credential id `telegram`. The same token
sends alerts and reads the user's replies.

You do the whole thing end to end with the **`sentinel_setup`** tool (the same API
the desktop connector uses): create the bot, store the token, detect the chat,
point Sentinel at it, and send a test — without making the user paste anything.

**Activate `hive.browser-automation` first** — this skill assumes you know the
lifecycle rules (the bridge attaches to the user's own Chrome; never launch or kill
a browser), the screenshot + viewport-fraction coordinate workflow, and
`hive-browser interact`. Telegram Web is a heavy SPA with custom rendering, so prefer the
screenshot + coordinate path over selectors when the snapshot is unclear.

### Telegram Web specifics (verified)

- Telegram Web defaults to the **K version** at `https://web.telegram.org/k/`. The
  selectors below are verified there; fall back to screenshot + coordinates if a
  selector doesn't match (e.g. the older `/a/` version).
- **Message composer:** `#editable-message-text` — click it, `type` your text, send
  with the Enter key. Used for `/newbot`, `/start`, etc.
- **Global search:** the search box is top-left (around `[0.13, 0.04]`). Click it,
  type a name, then click the result row to open that chat.
- **Read a bot's reply as text** (don't OCR a screenshot): run `hive-browser page
  text ".chat-message:last-child" --json` in the terminal — it returns the latest message verbatim — this is
  how you capture the token without transposing characters.

## Before you start — check what already exists

1. Run `sentinel_setup({"action": "status"})`. If it shows `telegram` already
   configured, the token's stored — skip to **Step 3 (detect the chat)** (or
   straight to **Step 4** if the colony config is already set), don't make a new
   bot.
2. Confirm the user is signed into Telegram: run `hive-browser open` /
   `hive-browser navigate https://web.telegram.org/k/ --json` in the terminal. **You cannot log in for them**
   — you don't have their phone or SMS code. If it shows a QR / phone-number login,
   STOP and ask the user to log into Telegram Web in their Chrome, then continue.
   Don't fight the login screen or try to switch login methods yourself.

## Step 1 — Create the bot with @BotFather

@BotFather is Telegram's official bot for managing bots.

1. **Use in-app search to reach BotFather — not `t.me/` URLs.** `t.me/BotFather`
   (and `hive-browser open`-ing it) tends to land on the t.me web page or redirect
   without opening the chat. Instead: click the global search box (top-left), type
   `BotFather`, and click the **verified** result (blue check) to open the chat.
2. In the BotFather chat, click the composer (`#editable-message-text`) and send
   `/newbot`. It asks for:
   - a **display name** (e.g. `Hive Sentinel`), then
   - a **username** that must end in `bot` (e.g. `hive_sentinel_<something>_bot`).
     If the name is taken, BotFather says so — pick another until it's accepted.
3. On success BotFather replies with **"Use this token to access the HTTP API:"**
   followed by the token `123456789:AAE…`. **Read it by running
   `hive-browser page text ".chat-message:last-child" --json` in the terminal, not off a screenshot** — the
   token is long and a single transposed character makes `store_token` fail. Copy
   the exact `digits:rest` string.

## Step 2 — Store the token

```
sentinel_setup({"action": "store_token", "provider": "telegram", "token": "123456789:AAE…"})
```

This validates the token via `getMe` before storing and reports the bot's
`@username`. If it's rejected, re-read the token from BotFather's message and retry
— never invent or pad a token.

> Prefer not to handle the token yourself? Fall back to
> `credentials(action="collect", …)` with `credential_id` `telegram` (field
> `access_token`) to pop a secure form. The default flow above is hands-off and is
> what the in-app "Set this up with the agent" button expects.

## Step 3 — Detect the chat to notify

Telegram bots can only message a user/group **after** that chat has messaged the
bot first. So trigger one message, then detect it:

1. Open the new bot's chat: **search its `@username`** (top-left search) and open
   the result — same as finding BotFather. (Clicking the `t.me/<bot>` link in
   BotFather's reply is less reliable; search is the sure path.)
2. Send `/start` (or any message): a fresh bot chat shows a **Start** button —
   click it; otherwise click the composer (`#editable-message-text`), type
   `/start`, and press Enter. Give it ~2–3s, then detect. That delivers the bot's
   first update.
   - **Group target instead?** Add the bot to the group, then send any message in
     that group. (You may need to disable BotFather's privacy mode via
     `/setprivacy → Disable` so the bot can read group messages.)
3. Run:

```
sentinel_setup({"action": "detect_chat"})
```

It returns the `chat_id` and the `sender_id`. Use the returned `sender_id` for the
allowlist so only that user can drive the colony.

`detect_chat` is **listener-aware**: if this bot is already wired to another colony,
Sentinel's background listener is long-polling Telegram and consuming updates — so a
raw `getUpdates` would always come back empty. The tool handles that for you (it
reads the chat the listener saw), so just call `detect_chat`. If it says **PENDING**,
the message simply hasn't landed yet — make sure Start/your message actually sent,
then retry. **Do not** start decrypting credentials or polling the Telegram API by
hand to debug a PENDING — that fights the listener and gets you nowhere; messaging
the bot and retrying is the whole fix.

## Step 4 — Turn Sentinel on and verify

`configure`/`test` target the colony bound to your session (pass `colony_id` only to
set up a different one):

```
sentinel_setup({"action": "configure", "channel": "telegram",
                "target": {"chat_id": "123456789"},
                "allowlist": ["123456789"], "enabled": true})
sentinel_setup({"action": "test"})
```

`test` sends a message to the chat — ask the user to confirm it arrived. If it
didn't, the usual causes are: the chat hasn't messaged the bot yet (redo Step 3),
the wrong `chat_id`, or (for groups) privacy mode still on. `sentinel_setup({"action":
"status"})` shows the stored token + the colony's current config any time.

When `test` succeeds you're done: tell the user Sentinel is live on Telegram and
they can reply to its messages to keep the colony moving. (They can review or change
this under **Automations → Set up Sentinel**.)

## Guardrails

- Activate `hive.browser-automation` and obey its lifecycle rules. Never run
  `google-chrome`/`chromium`, `--remote-debugging-port`, or kill any browser/bridge
  process — you drive the user's existing Chrome.
- **Reuse, don't duplicate.** If `sentinel_setup status` shows `telegram`
  configured, the bot already exists — use it; don't spin up another via
  `/newbot`.
- Never invent, guess, or paraphrase a token. Read it by running `hive-browser page
  text ".chat-message:last-child" --json` in the terminal, not off a screenshot, so you don't transpose a
  character; if `store_token` rejects it, re-read — don't pad or guess.
- **Don't try to log into Telegram for the user** — you can't enter their phone/SMS
  code. If Telegram Web shows a login screen, ask them to sign in, then continue.
- Reach BotFather and the bot via **in-app search**, not `t.me/` links (which often
  don't open the chat).
- The provider id is exact: `telegram`. The destination is `{"chat_id": "…"}` (a
  number as a string), not a username or link.
- A Telegram bot cannot initiate contact — if `detect_chat` stays PENDING, the user
  simply hasn't messaged the bot yet. Guide them to message it, then retry. Never
  decrypt the stored token, curl `getUpdates`, or otherwise debug the API by hand:
  the Sentinel listener owns the update stream, so manual polling just loses to it —
  `detect_chat` already reads what the listener saw.
