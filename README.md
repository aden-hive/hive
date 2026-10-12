<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/banner-dark.webp" />
    <img width="100%" alt="OpenHive. Describe the outcome; a queen agent grows the colony that gets it done." src="docs/assets/readme/banner-light.webp" />
  </picture>
</p>

<p align="center">
  <a href="README.md">English</a> |
  <a href="docs/i18n/zh-CN.md">简体中文</a> |
  <a href="docs/i18n/es.md">Español</a> |
  <a href="docs/i18n/hi.md">हिन्दी</a> |
  <a href="docs/i18n/pt.md">Português</a> |
  <a href="docs/i18n/ja.md">日本語</a> |
  <a href="docs/i18n/ru.md">Русский</a> |
  <a href="docs/i18n/ko.md">한국어</a>
</p>

<p align="center">
  <a href="https://github.com/aden-hive/hive/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-Apache%202.0-blue.svg" alt="Apache 2.0 License" /></a>
  <a href="https://www.ycombinator.com/companies/aden"><img src="https://img.shields.io/badge/Y%20Combinator-Aden-orange" alt="Y Combinator" /></a>
  <a href="https://discord.com/invite/MXE49hrKDk"><img src="https://img.shields.io/discord/1172610340073242735?logo=discord&labelColor=%235462eb&logoColor=%23f5f5f5&color=%235462eb" alt="Discord" /></a>
  <a href="https://x.com/aden_hq"><img src="https://img.shields.io/twitter/follow/teamaden?logo=X&color=%23f5f5f5" alt="Follow on X" /></a>
  <a href="https://www.linkedin.com/company/teamaden/"><img src="https://custom-icon-badges.demolab.com/badge/LinkedIn-0A66C2?logo=linkedin-white&logoColor=fff" alt="LinkedIn" /></a>
</p>

<h3 align="center">An open-source runtime for colonies of AI agents that do real business work.</h3>

<p align="center">
  Tell a queen agent what you need. She does the first piece herself to learn what the job takes, then hands the rest to as many parallel workers as it needs. Every result lands in a shared tracker you can query, audit and resume from.
</p>

<p align="center">
  <a href="docs/assets/readme/demo.mp4"><img width="100%" alt="Demo: a growth queen researches five products' Hacker News launches with a colony of parallel workers" src="docs/assets/readme/demo.webp" /></a>
  <br />
  <sub>A real run. Only the typing and the waiting are sped up, and the badge says by how much. <a href="docs/assets/readme/demo.mp4">Watch the full run (MP4)</a>.</sub>
</p>

## What you just watched

A growth team preparing a Show HN wants to know how five developer tools' own launches did on Hacker News. Here's what Hive did with that one message:

1. **You hand it to a queen.** Queens are long-lived agents with a role (here, Head of Growth) and their own memory and tools.
2. **She asks the one question that changes the answer:** every launch post, or only each product's original launch? You pick every launch, and she carries on.
3. **She proposes a colony, and you approve it.** Five products means five parallel jobs, so the chat becomes a colony: the queen plus as many worker agents as the work needs.
4. **She does one herself.** She takes PostHog first, works out what counts as a genuine launch post rather than a passing mention, checks the numbers against the Hacker News API, and saves the method as a reusable skill.
5. **She fans out.** A playbook starts one worker per product. Each follows her skill and writes its result to the colony's tracker, a shared SQLite table.
6. **She checks every row before she answers, and fixes one.** Cal.com's worker counted a post from its old name, Calendso, but that post wasn't a Show HN, Launch HN or YC launch. She clears the row, and the chart shows Cal.com as not found rather than zero.

None of this was wired up in advance. There's no workflow graph to draw: the queen shapes the colony as the work unfolds, and a tracker on disk, not a context window, keeps count of what's done and what's left.

## Quick start

**You'll need** Python 3.11+, Node.js 20+ and git. The quickstart installs `uv` and `ripgrep` if they're missing, and offers to install Node.

**And a model.** The quickstart sets up any of these:

- an API key from Anthropic, OpenAI, Google Gemini, Groq, Cerebras or OpenRouter
- a coding subscription you already pay for: Claude Code, OpenAI Codex, Kimi Code, MiniMax, Z.AI or Antigravity
- Hive LLM
- a local model through Ollama, with no key at all

```bash
git clone https://github.com/aden-hive/hive.git
cd hive
./quickstart.sh          # macOS / Linux
.\quickstart.ps1         # Windows (PowerShell 5.1+)
```

The quickstart creates a single Python environment for the workspace, stores your API key encrypted under `~/.hive`, asks which model to use, builds the dashboard and opens it at `http://127.0.0.1:8787`. Next time, run `hive open` from the repository.

> [!NOTE]
> Hive is a `uv` workspace, not a pip package. `pip install -e .` installs a placeholder that won't run; use the quickstart.

**Then** type a task on the home screen and choose the queen to give it to, or open the **Prompt Library** and send a ready-made prompt straight to the queen it was written for.

## How it works

```mermaid
flowchart LR
    You(["You"]) -->|"describe the outcome"| Queen["Queen<br/>(persistent agent)"]
    Queen -->|"proposes a colony,<br/>you approve"| Pilot["Pilot<br/>(one unit, done by the queen)"]
    Pilot -->|"saves the method"| Skill["Skill + playbook"]
    Skill -->|"run_worker / run_playbook"| W["Worker clones<br/>in parallel"]
    W -->|"tracker_upsert"| T[("Tracker<br/>shared SQLite")]
    T -->|"SQL: what's done,<br/>what's left"| Queen
    Queen -->|"checked answer"| You

    style Queen fill:#ffb100,stroke:#cc5d00,color:#333
    style T fill:#fff3d6,stroke:#cc5d00,color:#333
    style W fill:#ff9800,stroke:#cc5d00,color:#fff
```

Hive has **one execution primitive**: the agent loop. The queen is one, and every worker is a clone of it with its own task, a narrower set of tools and a strict budget. Orchestration is a tool call, not a compiled graph:

- **`run_worker`** fans tasks out and returns at once, so the queen keeps talking to you while workers run. Four run at a time by default; the rest wait their turn. Each worker's report arrives in the queen's conversation as a new turn.
- **The tracker** is the colony's shared state. The queen defines the table and which columns workers may write, workers upsert one row per unit of work, and the queen checks progress with SQL. It's a file on disk: `~/.hive/colonies/<name>/tracker/tracker.db`.
- **`run_playbook`** runs a proven method over every row, with retries and backoff, rate-limited lanes, and a dead-letter list for rows that keep failing. "What's left" is always a fresh query of the tracker, so re-running a playbook picks up where it stopped.

The **[architecture overview](docs/architecture/README.md)** goes deeper: the loop, the tool surface, memory, human oversight, and how state survives a crash.

<table>
  <tr>
    <td width="50%"><img alt="Home: the hive map of queens and colonies" src="docs/assets/readme/home.webp" /><br /><sub><b>Home.</b> Your queens and their colonies on one map. Describe a task and choose who takes it.</sub></td>
    <td width="50%"><img alt="A colony's workers running in parallel" src="docs/assets/readme/workers.webp" /><br /><sub><b>Workers.</b> One per unit of work, each with its own task and budget, all reporting to the queen.</sub></td>
  </tr>
  <tr>
    <td width="50%"><img alt="The colony tracker filling with results" src="docs/assets/readme/tracker.webp" /><br /><sub><b>Tracker.</b> Results land in a shared table as workers finish, ready to query, export or resume from.</sub></td>
    <td width="50%"><img alt="The queen's final answer with a sourced table and chart" src="docs/assets/readme/result.webp" /><br /><sub><b>Result.</b> A checked answer with sources and a chart, right in the chat.</sub></td>
  </tr>
</table>

## What's inside

**Queens with a job and a memory.** Hive ships thirteen persona queens. Six are active out of the box (Growth, RevOps, Content, Lead Generation, Outbound, and Brand & Design); hire the rest from the Org Chart, or create your own. Each one keeps notes in markdown memory as she works, and relevant past conversations are recalled into her context automatically.

**A memory you can measure.** A queen remembers you across sessions. She writes notes about you as she works, related past conversations are placed in front of her before each message, and she checks her memory before asking you for something you've already told her. We benchmark it on [LongMemEval](docs/memory-benchmark.md), run end to end through Hive and graded by the official judge, with `gpt-6.1-sol` answering:

| | LongMemEval-S | LongMemEval-M |
|---|---|---|
| History per question | ~115k tokens | ~1.1M tokens |
| **Hive** | **88.4%** | **82.0%** |
| The same model reading the whole history | 96.8% | doesn't fit |

When a whole history fits in the model's context, reading all of it is still more accurate than Hive's memory. When it doesn't, as on LongMemEval-M, memory is the only option. The [benchmark page](docs/memory-benchmark.md) has the methodology, per-type results, a comparison with other memory systems, and the limitations.

**Built-in tools that run in-process.** Shell commands and background jobs, file editing, fast code search, PDFs, attachments and images, web scraping, charts (ECharts and Mermaid), CSV files, and image generation through Hive LLM. They run inside Hive itself, with no tool servers to start.

**Your browser, driven by your agents.** The Hive Browser Bridge extension lets agents work in your own Chrome, where you're already logged in. Each worker gets its own tab group.

**Skills.** Reusable instructions in the open [Agent Skills](https://agentskills.io) format. Hive ships with a set, queens write new ones once a method proves out, and you manage them all in the Skills Library.

**Any MCP server.** Add one with `hive mcp add`, and its tools join the same allowlists as the built-ins. The full integration catalog in [`tools/`](tools/src/aden_tools/tools) (GitHub, Gmail, HubSpot, Slack, Notion and many more) runs as one; see [docs/tools.md](docs/tools.md).

**Runs while you're away.** Colonies can wake themselves on cron, interval or webhook triggers. **Sentinel**, opt-in per colony, watches a queen whenever she stops: it nudges her on, or escalates to you through the Hive inbox, Telegram or Slack, and she picks up as soon as you reply.

**Built to survive.** Every agent saves its state to disk and resumes exactly where it stopped after a crash or restart. Large tool results spill to files instead of flooding the context, long sessions compact themselves, stuck or looping turns get caught, and every worker runs under a hard tool-call budget.

**Any model.** Anything [LiteLLM](https://docs.litellm.ai/docs/providers) supports, including OpenAI, Anthropic, Gemini, OpenRouter, Hive LLM, any OpenAI-compatible endpoint and local models through Ollama. Workers can run on a different model than their queen, and text-only models still see images through a vision fallback.

## Is Hive for you?

Hive earns its keep once the model is no longer the hard part, and everything around it is:

- A process with **many similar units of work**, such as leads, accounts, tickets, repositories or documents, that you want done in parallel and done the same way every time.
- Work that **runs for hours or on a schedule** and has to survive a restart.
- Results you need to **check, query and audit**, not just read in a chat.
- A **human who stays in charge** of the decisions that matter.

For a single prompt or a one-off script, a plain agent is simpler.

## Documentation

- [Getting started](docs/getting-started.md): setup in more detail
- [Architecture overview](docs/architecture/README.md): how colonies, the loop, tools and memory fit together
- Key concepts: [colony](docs/key_concepts/colony.md), [queen](docs/key_concepts/queen.md), [workers](docs/key_concepts/worker_agent.md), [coordination](docs/key_concepts/coordination.md), [the loop](docs/key_concepts/the_loop.md), [goals and outcomes](docs/key_concepts/goals_outcome.md), [how colonies improve](docs/key_concepts/improvement.md)
- [Tools](docs/tools.md): built-in tools, MCP servers and the integration catalog
- [Configuration](docs/configuration.md) and the [developer guide](docs/developer-guide.md)
- [Memory benchmark](docs/memory-benchmark.md): LongMemEval results, methodology and limitations
- [Roadmap](docs/roadmap.md): what V1 ships and what's still open
- [docs.adenhq.com](https://docs.adenhq.com/): hosted documentation

## FAQ

**Which models does Hive support?**
Any provider [LiteLLM](https://docs.litellm.ai/docs/providers) supports, plus any OpenAI-compatible endpoint. The quickstart sets up the common ones, including coding subscriptions such as Claude Code and OpenAI Codex; [docs/configuration.md](docs/configuration.md) covers the rest.

**Can I run it with local models?**
Yes. Choose Ollama in the quickstart, or set a model such as `ollama/llama3` with Ollama running locally.

**How is this different from other agent frameworks?**
Most frameworks ask you to design a graph of agents and wire up their inputs and outputs. Hive has one kind of agent: the queen is an agent loop, and every worker is a clone of it. Orchestration happens at runtime through tool calls, and agents coordinate through a shared SQL tracker instead of passing messages along edges. Persistence, resume, budgets, compaction and oversight live in that one loop, so every agent gets them.

**Where does my data live?**
On your machine. Sessions, colonies, trackers and memory are plain files under `~/.hive` (or wherever `HIVE_HOME` points), and API keys are stored there encrypted.

**How do I keep costs under control?**
Every worker runs under hard limits on turns and tool calls, so a stuck worker stops by itself, and the number of workers running at once is capped. Every model call is metered. There are no spending limits in dollars yet.

**Can agents use my own tools and APIs?**
Yes: through the built-in shell and browser, through any MCP server you add, and through skills that teach them your procedures.

**Is Hive open source?**
Yes, under the [Apache License 2.0](LICENSE).

## Contributing

Contributions are welcome, especially tools, integrations and skills ([#2805](https://github.com/aden-hive/hive/issues/2805)). Read [CONTRIBUTING.md](CONTRIBUTING.md) first, and get assigned to an issue before you open a pull request: comment on the issue and a maintainer will assign you. Issues with reproduction steps or a concrete proposal get priority.

## Community

- [Discord](https://discord.com/invite/MXE49hrKDk) for questions, feature requests and discussion
- [X / Twitter](https://x.com/aden_hq) and [LinkedIn](https://www.linkedin.com/company/teamaden/) for updates
- [HoneyComb](http://honeycomb.open-hive.com/): a community market that tracks which jobs AI agents are automating. Go long or short on a job with compute tokens, not money.

**We're hiring** in engineering, research and go-to-market. [See open positions](https://jobs.adenhq.com/a8cec478-cdbc-473c-bbd4-f4b7027ec193/applicant).

## Security

To report a vulnerability, see [SECURITY.md](SECURITY.md).

## License

Apache License 2.0. See [LICENSE](LICENSE).

## Star history

<a href="https://www.star-history.com/?type=date&repos=aden-hive%2Fhive">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=aden-hive/hive&type=date&theme=dark&legend=top-left&sealed_token=vfX1DG8w_KTkonUUtIEjFRLvBopgDzxQpyb8hiYT22sobcDIpvQiMciZghLsDu5hyU3LJs-ZddFjl8eYFx5zRrY-kcMRsfyQ3vAiacsroPoqgRYmZaES3Q" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=aden-hive/hive&type=date&legend=top-left&sealed_token=vfX1DG8w_KTkonUUtIEjFRLvBopgDzxQpyb8hiYT22sobcDIpvQiMciZghLsDu5hyU3LJs-ZddFjl8eYFx5zRrY-kcMRsfyQ3vAiacsroPoqgRYmZaES3Q" />
   <img alt="Star history chart" src="https://api.star-history.com/chart?repos=aden-hive/hive&type=date&legend=top-left&sealed_token=vfX1DG8w_KTkonUUtIEjFRLvBopgDzxQpyb8hiYT22sobcDIpvQiMciZghLsDu5hyU3LJs-ZddFjl8eYFx5zRrY-kcMRsfyQ3vAiacsroPoqgRYmZaES3Q" />
 </picture>
</a>

---

<p align="center">Made with 🔥 passion in San Francisco</p>
