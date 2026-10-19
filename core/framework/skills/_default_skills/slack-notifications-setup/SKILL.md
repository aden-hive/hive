---
name: hive.slack-notifications-setup
description: Set up a Slack notification channel (Sentinel) for a colony by driving the browser — reuse or create the "Hive Sentinel" Slack app from a JSON manifest, install it, capture the bot + app tokens, create/select the channel via the Slack API, and turn Sentinel on so the colony can ping the user on Slack and accept replies. Use when the user asks to "set up Slack notifications", "get pinged on Slack", "connect Slack for alerts", "set up Sentinel on Slack", or clicks the in-app "Set this up with the agent" button on the Slack channel step. Requires hive.browser-automation.
metadata:
  author: hive
  type: default-skill
  version: "1.1"
  requires_skill: hive.browser-automation
---

# Slack Notifications Setup (Sentinel)

Sentinel pings the user on Slack when a colony stalls and lets them reply from
Slack to keep it going. It needs a Slack app with two tokens:

- a **Bot User OAuth Token** (`xoxb-…`) — stored under credential id `slack`, used to *send* alerts and call the Slack API.
- an **App-Level Token** (`xapp-…`) with `connections:write` — stored under credential id `slack_app`, used by Socket Mode to *receive* the user's reply.

You do the whole thing end to end: reuse-or-create the app, read the tokens, store
them with the **`sentinel_setup`** tool (the same API the desktop connector uses),
create/select the channel **via the Slack API**, and turn Sentinel on — without
making the user paste anything.

**Activate `hive.browser-automation` first** — this skill assumes you know the
lifecycle rules (the bridge attaches to the user's own Chrome; never launch or kill
a browser), the screenshot + viewport-fraction coordinate workflow, and
`hive-browser interact`.

## Before you start — check what already exists

1. Run `sentinel_setup({"action": "status"})`. If it shows **both** `slack bot` and
   `slack app` already configured, the app and tokens are already in place — skip
   Steps 1–4 entirely and go to **Step 5 (channel)**. Don't recreate anything.
2. Confirm the user is signed into the right Slack workspace: run
   `hive-browser navigate https://api.slack.com/apps --json` in the terminal. If it shows a sign-in screen,
   ask them to log into the workspace they want alerts in. If they have several
   workspaces, ask which one.
3. **Reuse before create.** Scan the apps list for an app named **Hive Sentinel**.
   If it exists, open it and skip to **Step 2** (app-level token) / **Step 3**
   (install) — do **not** create a second app. Only create one if none exists.

## Step 1 — Create the app from a JSON manifest

The manifest sets the name, bot scopes (including channel management), Socket Mode,
and event subscriptions in one shot.

1. Click **Create New App → From a manifest**, pick the workspace, click **Next**.
2. Switch to the **JSON** tab (not YAML — the browser type tools strip newlines and
   break YAML).
3. Inject the manifest with `hive-browser evaluate` (run in the terminal) using CodeMirror's API — see
   **"Filling the manifest editor"** below for the exact, non-doubling method. Use
   this manifest verbatim:

```json
{
  "display_information": { "name": "Hive Sentinel" },
  "features": { "bot_user": { "display_name": "Hive Sentinel", "always_online": true } },
  "oauth_config": {
    "scopes": {
      "bot": [
        "chat:write",
        "chat:write.public",
        "channels:read",
        "channels:history",
        "channels:manage",
        "groups:read",
        "groups:history",
        "users:read"
      ]
    }
  },
  "settings": {
    "event_subscriptions": { "bot_events": ["message.channels", "message.groups"] },
    "socket_mode_enabled": true,
    "org_deploy_enabled": false,
    "token_rotation_enabled": false
  }
}
```

`channels:manage` is included **up front** so you can create the channel by API in
Step 5 without ever reinstalling. Valid manifest keys only: `socket_mode_enabled`
(not `socket_mode`), and there is no `org_domains` field.

4. With the editor showing a single copy and no "can't translate" error, click
   **Next**, then **Create**.

### Filling the manifest editor (JSON tab — do this, nothing else)

Slack's manifest editor is **CodeMirror 5**, and it validates from React state, not
the DOM. Two traps, both avoided by the method below:

- `hive-browser interact`/`insert_text` **strips newlines** (breaks the manifest) and the
  type path tries to parse the braces. Don't type into it.
- A `paste`/`InputEvent` that **carries the text** gets *appended on top of* the
  current value — paste it after `setValue` and you get the manifest **twice**.

Set the value once, then fire a **value-less** input event so React re-reads it.
Run this with `hive-browser evaluate` in the terminal — because the script is
multi-line and quote-heavy, pass it via `--js -` (stdin) or `--js @file` rather than
inline `--js '…'`:

```js
// JSON tab must be active first (click the tab labelled "JSON").
const cm = document.querySelector('.CodeMirror').CodeMirror;
// Embed the manifest as a single-quoted JS string (it contains only double quotes).
const manifest = '{"display_information":{"name":"Hive Sentinel"}, ... }';
cm.setValue(manifest);                 // setValue REPLACES — it never appends
cm.getInputField().dispatchEvent(      // notify React WITHOUT carrying any text
  new InputEvent('input', { bubbles: true, inputType: 'insertFromPaste' })
);
return { valueLen: cm.getValue().length };  // sanity-check: one copy, not double
```

If `valueLen` is ~2× the manifest length, it doubled — `cm.setValue('')` then
`cm.setValue(manifest)` once and re-dispatch. Never solve a "Next is disabled" by
pasting again.

## Step 2 — Generate the App-Level Token (`xapp-…`)

Manifests can't mint app-level tokens. In the app: **Basic Information → App-Level
Tokens → Generate Token and Scopes**, name it (e.g. `socket`), add the scope
**`connections:write`**, **Generate**, then read the `xapp-…` value.

## Step 3 — Install to the workspace, get the Bot Token (`xoxb-…`)

1. Open **OAuth & Permissions** and click **Install to Workspace** → **Allow**.
2. Read the **Bot User OAuth Token** (`xoxb-…`). Read it from the input's value, not
   off a screenshot, so you don't truncate it:

```js
Array.from(document.querySelectorAll('input')).map(i => i.value).filter(v => v.startsWith('xoxb-'));
```

## Step 4 — Store both tokens with `sentinel_setup`

```
sentinel_setup({"action": "store_token", "provider": "slack",     "token": "xoxb-…"})
sentinel_setup({"action": "store_token", "provider": "slack_app", "token": "xapp-…"})
```

The bot token is validated (`auth.test`) before storing and reports the workspace.
If it's rejected, re-read the token from the input value (you likely grabbed a
partial string) and retry — never invent or pad a token.

> Prefer not to handle the tokens yourself? Fall back to
> `credentials(action="collect", …)` with `credential_id` `slack` / `slack_app`
> (field `access_token`) to pop a secure form. The default flow above is hands-off
> and is what the in-app "Set this up with the agent" button expects.

## Step 5 — Channel: do it with the Slack API, not the UI

Don't click around the Slack web UI to make or find a channel — use the Slack API
with the bot token via `terminal_exec` + `curl`. (A browser `fetch()` to slack.com
is **CORS-blocked** from the app tab; curl from the terminal is the reliable path.)

**Reuse an existing channel** the user named — list and grab its `id`:

```bash
curl -s -X POST 'https://slack.com/api/conversations.list' \
  -H 'Authorization: Bearer xoxb-…' \
  -H 'Content-Type: application/x-www-form-urlencoded' \
  -d 'types=public_channel,private_channel&limit=1000'
```

**Create a dedicated channel** (recommended default, e.g. `hive-sentinel`). The bot
joins automatically as the creator, and the response carries the new channel `id`:

```bash
curl -s -X POST 'https://slack.com/api/conversations.create' \
  -H 'Authorization: Bearer xoxb-…' \
  -H 'Content-Type: application/json' \
  -d '{"name":"hive-sentinel","is_private":false}'
```

If you **reuse** a channel the bot didn't create, add the bot so it can post and
read replies (look up the bot user id from `auth.test` if needed):

```bash
curl -s -X POST 'https://slack.com/api/conversations.invite' \
  -H 'Authorization: Bearer xoxb-…' -H 'Content-Type: application/json' \
  -d '{"channel":"C0123ABC456","users":"<BOT_USER_ID>"}'
```

Take the channel `id` (`C…`) from the JSON response. `channels:manage` is already in
the manifest, so none of this needs a reinstall.

## Step 6 — Turn Sentinel on and verify

`configure`/`test` target the colony bound to your session (pass `colony_id` only to
set up a different one):

```
sentinel_setup({"action": "configure", "channel": "slack",
                "target": {"channel": "C0123ABC456"}, "enabled": true})
sentinel_setup({"action": "test"})
```

`test` posts to the channel — ask the user to confirm it arrived. If it didn't, the
usual causes are the bot isn't in the channel (re-run `conversations.invite`) or the
channel id is wrong. `sentinel_setup({"action": "status"})` shows stored tokens +
the colony's current config any time.

When `test` succeeds you're done: tell the user Sentinel is live on `#<channel>` and
they can reply to its messages from Slack to keep the colony moving. (They can review
or change any of this under **Automations → Set up Sentinel**.)

## Guardrails

- Activate `hive.browser-automation` and obey its lifecycle rules. Never run
  `google-chrome`/`chromium`, `--remote-debugging-port`, or kill any browser/bridge
  process — you drive the user's existing Chrome.
- **Reuse, don't duplicate.** If a **Hive Sentinel** app already exists (or
  `sentinel_setup status` shows both tokens configured), use it — never create a
  second app.
- Never invent, guess, or paraphrase a token. If you can't read one cleanly, re-read
  the input value rather than fabricating.
- The two `store_token` providers are exact: `slack` (bot, `xoxb-`) and `slack_app`
  (app-level, `xapp-`). Swapping them breaks send vs. receive.
- Manifest editor: **JSON tab + `cm.setValue` once + a value-less `input` event**.
  Never type the manifest, never use the YAML tab, never re-paste to "fix" a
  disabled Next button (that doubles the content).
- If Slack shows an org/admin approval wall on install, the workspace requires admin
  approval for apps — tell the user to request it (or use a workspace where they're
  admin); you can't bypass it.
