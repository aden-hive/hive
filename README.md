<p align="center">
  <img width="100%" alt="Hive Banner" src="https://asset.acho.io/github/img/banner.gif" />
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
  <a href="https://x.com/aden_hq"><img src="https://img.shields.io/twitter/follow/teamaden?logo=X&color=%23f5f5f5" alt="Twitter Follow" /></a>
  <a href="https://www.linkedin.com/company/teamaden/"><img src="https://custom-icon-badges.demolab.com/badge/LinkedIn-0A66C2?logo=linkedin-white&logoColor=fff" alt="LinkedIn" /></a>
  <img src="https://img.shields.io/badge/MCP-102_Tools-00ADD8?style=flat-square" alt="MCP" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Agent_Harness-Runtime_Layer-ff6600?style=flat-square" alt="Agent Harness" />
  <img src="https://img.shields.io/badge/AI_Agents-Self--Improving-brightgreen?style=flat-square" alt="AI Agents" />
  <img src="https://img.shields.io/badge/Multi--Agent-Systems-blue?style=flat-square" alt="Multi-Agent" />
  <img src="https://img.shields.io/badge/Headless-Development-purple?style=flat-square" alt="Headless" />
  <img src="https://img.shields.io/badge/Human--in--the--Loop-orange?style=flat-square" alt="HITL" />
  <img src="https://img.shields.io/badge/Browser-Use-red?style=flat-square" alt="Browser Use" />
</p>
<p align="center">
  <img src="https://img.shields.io/badge/OpenAI-supported-412991?style=flat-square&logo=openai" alt="OpenAI" />
  <img src="https://img.shields.io/badge/Anthropic-supported-d4a574?style=flat-square" alt="Anthropic" />
  <img src="https://img.shields.io/badge/Google_Gemini-supported-4285F4?style=flat-square&logo=google" alt="Gemini" />
</p>

<p align="center"><em>The agent harness for production workloads — state management, failure recovery, observability, and human oversight so your agents actually run.</em></p>

## Overview

OpenHive is a zero-setup, model-agnostic execution harness that dynamically generates multi-agent topologies to tackle complex, long-running business workflows without requiring any orchestration boilerplate. By simply defining your objective, the runtime compiles a strict, graph-based execution DAG that safely coordinates specialized agents to execute concurrent tasks in parallel. Backed by persistent, role-based memory that intelligently evolves with your project's context, OpenHive ensures deterministic fault tolerance, deep state observability, and seamless asynchronous execution across whichever underlying LLMs you choose to plug in.

## Features

- ✅ Multi-Agent Coordination for parallel task execution 
- ✅ Graph-based execution for recurring and complex processes 
- ✅ Role-based memory that evolves with your projects 
- ✅ Zero Setup - No technical configuration required
- ✅ General Compute Use and Browser Use with Native Extension 
- ✅ Custom Model Support

Visit [adenhq.com](https://adenhq.com) for complete documentation, examples, and guides.

Visit [HoneyComb](http://honeycomb.open-hive.com/) to see what jobs are being automated by AI. It’s a stock market for jobs, driven by our community’s AI agent progress. You can long and short jobs (with no real money but compute token)based on how much you think a job is going to be replaced by AI.

https://github.com/user-attachments/assets/bf10edc3-06ba-48b6-98ba-d069b15fb69d


## Who Is Hive For?

Hive is the multi-agent harness layer for teams moving AI agents from prototype to production. Single agents like Openclaw and Cowork can finish personal jobs pretty well but lack the rigor to fulfil business processes. 

Hive is a good fit if you:

- Want AI agents that **execute real business processes**, not demos
- Need a **runtime that handles state, recovery, and parallel execution** at scale
- Need **self-healing and adaptive agents** that improve over time
- Require **human-in-the-loop control**, observability, and cost limits
- Plan to run agents in **production** where uptime, cost, and auditability matter

Hive may not be the best fit if you’re only experimenting with simple agent chains or one-off scripts.

## When Should You Use Hive?

Use Hive when the bottleneck is no longer the model but the harness around it:

- Long-running agents that need **state persistence and crash recovery**
- Production workloads requiring **cost enforcement, observability, and audit trails**
- Agents that **self-heal** through failure capture and graph evolution
- Multi-agent coordination with **session isolation and shared buffers**
- A framework that **scales with model improvements** rather than fighting them

## Quick Links

- **[Documentation](https://docs.adenhq.com/)** - Complete guides and API reference
- **[Self-Hosting Guide](https://docs.adenhq.com/getting-started/quickstart)** - Deploy Hive on your infrastructure
- **[Changelog](https://github.com/aden-hive/hive/releases)** - Latest updates and releases
- **[Roadmap](docs/roadmap.md)** - Upcoming features and plans
- **[Report Issues](https://github.com/aden-hive/hive/issues)** - Bug reports and feature requests
- **[Contributing](CONTRIBUTING.md)** - How to contribute and submit PRs

## Quick Start

### Prerequisites

- Python 3.11+ for agent development
- An LLM provider that powers the agents
- **ripgrep (optional, recommended on Windows):** The `search_files` tool uses ripgrep for faster file search. If not installed, a Python fallback is used. On Windows: `winget install BurntSushi.ripgrep` or `scoop install ripgrep`

> **Windows Users:** Native Windows is supported via `quickstart.ps1` and `hive.ps1`. Run these in PowerShell 5.1+. WSL is also an option but not required.

### Installation

> **Note**
> Hive uses a `uv` workspace layout and is not installed with `pip install`.
> Running `pip install -e .` from the repository root will create a placeholder package and Hive will not function correctly.
> Please use the quickstart script below to set up the environment.

```bash
# Clone the repository
git clone https://github.com/aden-hive/hive.git
cd hive

# Run quickstart setup (macOS/Linux)
./quickstart.sh

# Windows (PowerShell)
.\quickstart.ps1
```

This sets up:

- **framework** - Core agent runtime and graph executor (in `core/.venv`)
- **aden_tools** - MCP tools for agent capabilities (in `tools/.venv`)
- **credential store** - Encrypted API key storage (`~/.hive/credentials`)
- **LLM provider** - Interactive default model configuration, including Hive LLM and OpenRouter
- All required Python dependencies with `uv`

- Finally, it will open the Hive interface in your browser

> **Tip:** To reopen the dashboard later, run `hive open` from the project directory.

### First-Run Troubleshooting

A few setup blockers are easy to hit on first run. Checking these before debugging agent behavior can save time:

- **Verify your LLM provider credits/quota first.** Hive can start planning and executing quickly, so free-tier or low-credit accounts may fail before a full run completes.
- **Connect required tools before testing search-heavy workflows.** Some agents depend on integrations such as web search or external services. If the required tool is not connected, results may be incomplete or the workflow may fail.
- **Expect some sample agents to require credentials.** Template agents such as inbox, research, or external-data workflows may not be runnable until their required credentials are configured.
- **Google account setup may vary by account type.** Some Google-managed or workspace accounts may hit OAuth/admin restrictions depending on account policy.
- **If a run appears stalled, check provider limits before deeper debugging.** Provider rate limits, exhausted quota, or missing credentials can look like product issues on first run.

> **Tip:** If a workflow depends on external tools or provider credits, confirm those are configured before evaluating agent behavior in the UI.

### Build Your First Agent

Type the agent you want to build in the home input box. The queen is going to ask you questions and work out a solution with you.

<img width="2500" height="1214" alt="Image" src="https://github.com/user-attachments/assets/1ce19141-a78b-46f5-8d64-dbf987e048f4" />

### Use Template Agents

Click "Try a sample agent" and check the templates. You can run a template directly or choose to build your version on top of the existing template.

### Run Agents

Now you can run an agent by selecting the agent (either an existing agent or example agent). You can click the Run button on the top left, or talk to the queen agent and it can run the agent for you.

<img width="2549" height="1174" alt="Screenshot 2026-03-12 at 9 27 36 PM" src="https://github.com/user-attachments/assets/7c7d30fa-9ceb-4c23-95af-b1caa405547d" />

## Integration

<a href="https://github.com/aden-hive/hive/tree/main/tools/src/aden_tools/tools"><img width="100%" alt="Integration" src="https://github.com/user-attachments/assets/a1573f93-cf02-4bb8-b3d5-b305b05b1e51" /></a>
Hive is built to be model-agnostic and system-agnostic.

- **LLM flexibility** - Hive Framework supports Anthropic, OpenAI, OpenRouter, Hive LLM, and other hosted or local models through LiteLLM-compatible providers.
- **Business system connectivity** - Hive Framework is designed to connect to all kinds of business systems as tools, such as CRM, support, messaging, data, file, and internal APIs via MCP.

## Why Hive

As models improve, the upper bound of what agents can do rises — but their reliability and production value are determined by the harness. Hive focuses on generating agents that run real business processes rather than generic agents. Instead of requiring you to manually design workflows, define agent interactions, and handle failures reactively, Hive flips the paradigm: **you describe outcomes, and the system builds itself**—delivering an outcome-driven, adaptive experience with an easy-to-use set of tools and integrations.

```mermaid
flowchart LR
    GOAL["Define Goal"] --> GEN["Auto-Generate Graph"]
    GEN --> EXEC["Execute Agents"]
    EXEC --> MON["Monitor & Observe"]
    MON --> CHECK{{"Pass?"}}
    CHECK -- "Yes" --> DONE["Deliver Result"]
    CHECK -- "No" --> EVOLVE["Evolve Graph"]
    EVOLVE --> EXEC

    GOAL -.- V1["Natural Language"]
    GEN -.- V2["Instant Architecture"]
    EXEC -.- V3["Easy Integrations"]
    MON -.- V4["Full visibility"]
    EVOLVE -.- V5["Adaptability"]
    DONE -.- V6["Reliable outcomes"]

    style GOAL fill:#ffbe42,stroke:#cc5d00,stroke-width:2px,color:#333
    style GEN fill:#ffb100,stroke:#cc5d00,stroke-width:2px,color:#333
    style EXEC fill:#ff9800,stroke:#cc5d00,stroke-width:2px,color:#fff
    style MON fill:#ff9800,stroke:#cc5d00,stroke-width:2px,color:#fff
    style CHECK fill:#fff59d,stroke:#ed8c00,stroke-width:2px,color:#333
    style DONE fill:#4caf50,stroke:#2e7d32,stroke-width:2px,color:#fff
    style EVOLVE fill:#e8763d,stroke:#cc5d00,stroke-width:2px,color:#fff
    style V1 fill:#fff,stroke:#ed8c00,stroke-width:1px,color:#cc5d00
    style V2 fill:#fff,stroke:#ed8c00,stroke-width:1px,color:#cc5d00
    style V3 fill:#fff,stroke:#ed8c00,stroke-width:1px,color:#cc5d00
    style V4 fill:#fff,stroke:#ed8c00,stroke-width:1px,color:#cc5d00
    style V5 fill:#fff,stroke:#ed8c00,stroke-width:1px,color:#cc5d00
    style V6 fill:#fff,stroke:#ed8c00,stroke-width:1px,color:#cc5d00
```

### How It Works

1. **[Define Your Goal](docs/key_concepts/goals_outcome.md)** → Describe what you want to achieve in plain English
2. **Coding Agent Generates** → Creates the [agent graph](docs/key_concepts/graph.md), connection code, and test cases
3. **[Workers Execute](docs/key_concepts/worker_agent.md)** → SDK-wrapped nodes run with full observability and tool access
4. **Control Plane Monitors** → Real-time metrics, budget enforcement, policy management
5. **[Adaptiveness](docs/key_concepts/evolution.md)** → On failure, the system evolves the graph and redeploys automatically

## Documentation

- **[Developer Guide](docs/developer-guide.md)** - Comprehensive guide for developers
- [Getting Started](docs/getting-started.md) - Quick setup instructions
- [Configuration Guide](docs/configuration.md) - All configuration options
- [Architecture Overview](docs/architecture/README.md) - System design and structure

## Contributing
We welcome contributions from the community! We’re especially looking for help building tools, integrations, and example agents for the framework ([check #2805](https://github.com/aden-hive/hive/issues/2805)). If you’re interested in extending its functionality, this is the perfect place to start. Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

**Important:** Please get assigned to an issue before submitting a PR. Comment on an issue to claim it, and a maintainer will assign you. Issues with reproducible steps and proposals are prioritized. This helps prevent duplicate work.

1. Find or create an issue and get assigned
2. Fork the repository
3. Create your feature branch (`git checkout -b feature/amazing-feature`)
4. Commit your changes (`git commit -m 'Add amazing feature'`)
5. Push to the branch (`git push origin feature/amazing-feature`)
6. Open a Pull Request

## Community & Support

We use [Discord](https://discord.com/invite/MXE49hrKDk) for support, feature requests, and community discussions.

- Discord - [Join our community](https://discord.com/invite/MXE49hrKDk)
- Twitter/X - [@adenhq](https://x.com/aden_hq)
- LinkedIn - [Company Page](https://www.linkedin.com/company/teamaden/)

## Join Our Team

**We're hiring!** Join us in engineering, research, and go-to-market roles.

[View Open Positions](https://jobs.adenhq.com/a8cec478-cdbc-473c-bbd4-f4b7027ec193/applicant)

## Security

For security concerns, please see [SECURITY.md](SECURITY.md).

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.

## Frequently Asked Questions (FAQ)

**Q: What LLM providers does Hive support?**

Hive supports 100+ LLM providers through LiteLLM integration, including OpenAI (GPT-4, GPT-4o), Anthropic (Claude models), Google Gemini, DeepSeek, Mistral, Groq, OpenRouter, and Hive LLM. Simply set the appropriate API key environment variable and specify the model name. See [docs/configuration.md](docs/configuration.md) for provider-specific configuration examples.

**Q: Can I use Hive with local AI models like Ollama?**

Yes! Hive supports local models through LiteLLM. Simply use the model name format `ollama/model-name` (e.g., `ollama/llama3`, `ollama/mistral`) and ensure Ollama is running locally.

**Q: What makes Hive different from other agent frameworks?**

Hive is an agent harness, not just an orchestration framework. It provides the production runtime layer — session isolation, checkpoint-based crash recovery, cost enforcement, real-time observability, and human-in-the-loop controls — that makes agents reliable enough to run real workloads. On top of that, Hive generates your entire agent system from natural language goals and automatically [evolves the graph](docs/key_concepts/evolution.md) when agents fail. The combination of a robust harness with self-improving generation is what sets Hive apart.

**Q: Is Hive open-source?**

Yes, Hive is fully open-source under the Apache License 2.0. We actively encourage community contributions and collaboration.

**Q: Does Hive support human-in-the-loop workflows?**

Yes, Hive fully supports [human-in-the-loop](docs/key_concepts/graph.md#human-in-the-loop) workflows through intervention nodes that pause execution for human input. These include configurable timeouts and escalation policies, allowing seamless collaboration between human experts and AI agents.

**Q: What programming languages does Hive support?**

The Hive framework is built in Python. A JavaScript/TypeScript SDK is on the roadmap.

**Q: Can Hive agents interact with external tools and APIs?**

Yes. Aden's SDK-wrapped nodes provide built-in tool access, and the framework supports flexible tool ecosystems. Agents can integrate with external APIs, databases, and services through the node architecture.

**Q: How does cost control work in Hive?**

Hive provides granular budget controls including spending limits, throttles, and automatic model degradation policies. You can set budgets at the team, agent, or workflow level, with real-time cost tracking and alerts.

**Q: Where can I find examples and documentation?**

Visit [docs.adenhq.com](https://docs.adenhq.com/) for complete guides, API reference, and getting started tutorials. The repository also includes documentation in the `docs/` folder and a comprehensive [developer guide](docs/developer-guide.md).

**Q: How can I contribute to Aden?**

Contributions are welcome! Fork the repository, create your feature branch, implement your changes, and submit a pull request. See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

## Star History

<a href="https://star-history.com/#aden-hive/hive&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=aden-hive/hive&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=aden-hive/hive&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=aden-hive/hive&type=Date" />
 </picture>
</a>

---

<p align="center">
  Made with 🔥 Passion in San Francisco
</p>
