# Building on Hive

Hive's primitives (the agent loop, model providers, tools, events and configuration) can be
used by your own project. Depend on the `aden-hive` package and import them from `hive`.

## Install

Hive is on PyPI as `aden-hive`:

```toml
# pyproject.toml
[project]
dependencies = ["aden-hive[server]>=1.0.1,<2"]
```

The base install brings only what the primitives need. The extras are:

| Extra | Adds | Needed for |
|---|---|---|
| `server` | aiohttp | `SSEResponse`, and serving your own pages |
| `tools` | `aden-tools`: Hive's built-in tools (terminal, files, memory, charts, PDFs, scraping, spreadsheets) and the browser, with their libraries | queens, colonies and their workers; the whole Hive app |

`pip install "aden-hive[tools]"` installs the whole Hive app, dashboard included: run `hive open`.
The terminal tools also need [ripgrep](https://github.com/BurntSushi/ripgrep) on your `PATH`.

## Start a project

Copy [`templates/derivative/AGENTS.md`](../templates/derivative/AGENTS.md) to your repository's root
and fill in its overview and commands. It is an [AGENTS.md](https://agents.md) that tells coding
agents how to build on Hive: the rules below, a working example, how to test without a model, and
the gotchas.

## Use

```python
from hive import AgentContext, AgentLoop, AgentReport, AgentSpec, LiteLLMProvider, LoopConfig, ToolResult, ToolUse

reports: list[AgentReport] = []


async def run_tool(call: ToolUse) -> ToolResult:
    return ToolResult(tool_use_id=call.id, content="It is raining.")


spec = AgentSpec(id="scout", name="Scout", description="Looks around", system_prompt="Look outside, then report.")
llm = LiteLLMProvider(model="anthropic/claude-sonnet-5-5")
ctx = AgentContext(runtime=None, agent_id="scout", agent_spec=spec, llm=llm, available_tools=[...])
loop = AgentLoop(tool_executor=run_tool, config=LoopConfig(max_iterations=4), on_report=reports.append)
result = await loop.execute(ctx)
```

- **`on_report`** gives the agent a `report_to_parent` tool and receives its `AgentReport`
  (`status`, `summary` and `data` following the spec's `report_schema`). The loop ends once
  the agent reports.
- **The user's Hive setup** is available: `HIVE_HOME`, `get_preferred_model()`, `get_api_key()`,
  `get_api_base()` and `RuntimeConfig` read the model and keys configured with the quickstart.
- **`import hive` is cheap.** Each name is imported when first used.
- **Stability:** names exported from `hive` follow semantic versioning from 1.0.1. Anything
  imported from `framework.*` is Hive's internals and may change in any release.

## Channels: reach queens from a chat app

A channel runs inside `hive serve` and connects a chat app to a queen. Each conversation in the
app (a group, a private chat) is one queen session, which also shows in the dashboard. Users
install it as an [optional package](optional-packages.md); point your README there.

Register a factory in the `hive.channels` entry-point group:

```toml
[project.entry-points."hive.channels"]
mychat = "mychat:MyChatChannel"
```

`hive serve` calls it with a `ChannelHost` and starts the object it returns when the user turns
the channel on in `configuration.json`:

```json
{"channels": {"mychat": {"enabled": true, "token": "..."}}}
```

```python
from hive import ChannelError, ChannelHost, QueenOutput


class MyChatChannel:
    def __init__(self, host: ChannelHost) -> None:
        self.host = host  # host.config is the channel's section above; host.state_dir is for its files

    async def start(self) -> None: ...  # connect, then return; the work runs in background tasks

    async def stop(self) -> None: ...

    async def on_chat_message(self, chat_id: str, text: str, images: list[bytes]) -> None:
        session_id = await self.host.open_session("queen_growth", session_id=self.saved.get(chat_id), title=f"MyChat · {chat_id}")
        self.host.subscribe(session_id, lambda out: self.reply(chat_id, out))
        await self.host.send(session_id, text, images=images)

    async def reply(self, chat_id: str, out: QueenOutput) -> None:
        ...  # out.kind is "message", "question" (out.questions), "files" (out.files) or "error"
```

- **`open_session`** resumes the conversation's earlier session, or starts a new one named `title`.
  Keep the id it returns.
- **`send`** resumes a stopped session itself and saves `images` like dashboard attachments. It
  returns the session that took the message: it differs after the queen moves the conversation on.
  It raises `ChannelError` when the session is locked; open a new one.
- **`subscribe`** hears each finished model turn's text, each `ask_user` question, the files she
  hands over with `attach_file`, and each failed model call, in order, including after the session is resumed and for messages typed in the
  dashboard.
- **`judge`** asks the judge in the `judge` slot (Settings → AI Model → Judge) a yes/no question
  about the `state` you pass, and returns the probability of yes, or `None` when no judge is set
  up or it can't answer now. A channel can use it to decide, say, whether the queen should speak
  up in a group without being addressed. Each call is one request to the judge's vendor.
- The dashboard leaves channel sessions alone: opening the queen or starting a new chat with her
  never picks or stops one. `GET /api/channels` lists installed channels as `running`, `off` or
  `failed` (with the error).

## Turn context: show a queen something before each turn

A turn-context package runs inside `hive serve`. Before a queen answers a user message, it gets
her id and the message, and the text it returns reaches her as a `<system-reminder>` just ahead of
that message. Use it for context that depends on what was said: examples in her voice, notes
from your own store. Users install it as an [optional package](optional-packages.md).

Register a factory in the `hive.turn_context` entry-point group:

```toml
[project.entry-points."hive.turn_context"]
mycontext = "mycontext:MyContext"
```

`hive serve` calls it with a `TurnContextHost` and starts the object it returns when the user
turns it on in `configuration.json`:

```json
{"turn_context": {"mycontext": {"enabled": true}}}
```

```python
from hive import TurnContextHost


class MyContext:
    def __init__(self, host: TurnContextHost) -> None:
        self.host = host  # host.config is the section above; host.state_dir is for its files

    async def start(self) -> None: ...  # return quickly; load models or indexes in a background task

    async def stop(self) -> None: ...

    async def context(self, queen_id: str, message: str) -> str | None:
        return None  # or the text she should see before answering
```

- `message` is what the queen receives, including any prefix a channel adds (sender, time, recent
  group chat).
- Return `None` when there is nothing to add. The text stays in the conversation like any reminder,
  so keep it short.
- A package that takes longer than 5 seconds or raises is skipped for that turn; one that fails to
  start is logged and left out. Neither holds the turn.
