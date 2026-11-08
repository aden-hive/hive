# Hive desktop (GPUI)

A native Hive client drawn with [GPUI](https://github.com/zed-industries/zed) through
[GPUI Kit](https://gpui-kit.com). It talks to a running `hive serve` over the same HTTP API as the
web dashboard, so the server needs no changes.

## What it covers

- **Queens:** direct chats.
  - Open her running chat, switch between her past chats, start a new one, rename one, or branch a
    new chat from before any of your messages.
  - Replies render as Markdown, with thinking, tool calls (terminal output and chart pictures
    included) and images you sent.
  - Answer her `ask_user` questions with buttons or your own words. Fill in a credential she
    asks for. Approve or deny a skill she wants to install for everyone. Accept or decline a colony
    she suggests.
  - Attach images and files, stop a turn, copy any message, see her plan and how full her context is.
- **Colonies:** the same chat, plus a side panel.
  - Workers: status, transcript, stop one or all.
  - Plan.
  - Schedules: add, pause or resume, run now.
  - Data: the colony's tables.
  - Rename or delete the colony. New colonies are started from the sidebar.
- **Pages:** Home, Org chart, each queen's Profile, Models, Credentials, Skills, Tools (MCP servers
  included), Prompts, Memory and Settings.
- **Keeping up:**
  - The sidebar shows which queens and colonies are working or waiting for you.
  - A banner appears when the server can't reach the model provider.
  - A dropped stream reconnects, and a session is resumed after the server restarts.
- **Long chats:** only the messages on screen are laid out, so a long chat stays as quick as a short one.
- **Between runs:** the window keeps its place and size, and the app reopens the page you left (per
  server). Light or dark follows the system.

## Build and run

Needs stable Rust. On Windows, it also needs the MSVC build tools and a Windows SDK.

```sh
cargo run --release                                   # talks to http://127.0.0.1:8787
cargo run --release -- --server http://127.0.0.1:8797 # or another server
HIVE_URL=http://127.0.0.1:8797 cargo run --release    # same, from the environment
cargo run --release -- --open queen:queen_growth      # start on a page: home, models, colony:<name>, profile:<id>, …
```

`cargo test` runs the unit tests: event replay, answer formats, paths, and parsing.

## Layout

- `src/api.rs`: the HTTP calls and the event-stream reader. They block, so views run them through `bg.rs`.
- `src/chat.rs`: replays session events into chat items. It mirrors `replayEvent` in
  `frontend/src/lib/chat-helpers.ts`.
- `src/chat_view.rs`: a chat (queen or colony) and what the queen asks of you in it.
- `src/colony_view.rs`: a colony's chat and side panel.
- `src/shell.rs`: the window frame and sidebar, and routing between views.
- `src/live.rs`: the running sessions, for status dots.
- `src/pages/`: one file per page.
- `src/state.rs`: what's remembered between runs.
