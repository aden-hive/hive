<p align="center">
  <img width="100%" alt="Hive Banner" src="https://github.com/user-attachments/assets/a027429b-5d3c-4d34-88e4-0feaeaabbab3" />
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

Hive is a runtime harness for AI agents in production. You describe your goal in natural language; a coding agent (the queen) generates the agent graph and connection code to achieve it. During execution, the harness manages state isolation, checkpoint-based crash recovery, cost enforcement, and real-time observability. When agents fail, the framework captures failure data, evolves the graph through the coding agent, and redeploys automatically. Built-in human-in-the-loop nodes, browser control, credential management, and parallel execution give you production reliability without sacrificing adaptability.

Visit [adenhq.com](https://adenhq.com) for complete documentation, examples, and guides.

Visit [HoneyComb](http://honeycomb.open-hive.com/) to see what jobs are being automated by AI. It’s a stock market for jobs, driven by our community’s AI agent progress. You can long and short jobs (with no real money but compute token)based on how much you think a job is going to be replaced by AI.

https://github.com/user-attachments/assets/bf10edc3-06ba-48b6-98ba-d069b15fb69d


## Who Is Hive For?

Hive is the harness layer for teams moving AI agents from prototype to production. Models are getting better on their own — the bottleneck is the infrastructure around them: state management, failure recovery, cost control, and observability.

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
- Multi-agent coordination with **session isolation and shared memory**
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

### Build Your First Agent

Type the agent you want to build in the home input box. The queen is going to ask you questions and work out a solution with you.

<img width="2500" height="1214" alt="Image" src="https://github.com/user-attachments/assets/1ce19141-a78b-46f5-8d64-dbf987e048f4" />

### Use Template Agents

Click "Try a sample agent" and check the templates. You can run a template directly or choose to build your version on top of the existing template.

### Run Agents

Now you can run an agent by selecting the agent (either an existing agent or example agent). You can click the Run button on the top left, or talk to the queen agent and it can run the agent for you.

<img width="2549" height="1174" alt="Screenshot 2026-03-12 at 9 27 36 PM" src="https://github.com/user-attachments/assets/7c7d30fa-9ceb-4c23-95af-b1caa405547d" />

## Features

- **Browser-Use** - Control the browser on your computer to achieve hard tasks
- **Parallel Execution** - Execute the generated graph in parallel. This way you can have multiple agents completing the jobs for you
- **[Goal-Driven Generation](docs/key_concepts/goals_outcome.md)** - Define objectives in natural language; the coding agent generates the agent graph and connection code to achieve them
- **[Adaptiveness](docs/key_concepts/evolution.md)** - Framework captures failures, calibrates according to the objectives, and evolves the agent graph
- **[Dynamic Node Connections](docs/key_concepts/graph.md)** - No predefined edges; connection code is generated by any capable LLM based on your goals
- **SDK-Wrapped Nodes** - Every node gets shared memory, local RLM memory, monitoring, tools, and LLM access out of the box
- **[Human-in-the-Loop](docs/key_concepts/graph.md#human-in-the-loop)** - Intervention nodes that pause execution for human input with configurable timeouts and escalation
- **Real-time Observability** - WebSocket streaming for live monitoring of agent execution, decisions, and node-to-node communication

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

### The Hive Advantage

| Typical Agent Frameworks   | Hive                                   |
| -------------------------- | -------------------------------------- |
| Focus on model orchestration | **Production harness**: state, recovery, observability |
| Hardcode agent workflows   | Describe goals in natural language     |
| Manual graph definition    | Auto-generated agent graphs            |
| Reactive error handling    | Outcome-evaluation and adaptiveness    |
| Static tool configurations | Dynamic SDK-wrapped nodes              |
| Separate monitoring setup  | Built-in real-time observability       |
| DIY budget management      | Integrated cost controls & degradation |



## From Workflows to Outcome-Driven Agents

If you’re coming from workflow-first frameworks (where you manually wire steps, tools, and edges), Hive uses a different mental model: **you describe the outcome, and the system generates and evolves the execution graph**.

### Goals Instead of Hardcoded Workflows
Traditional agent systems require you to define a fixed workflow graph up front.  
In Hive, you define the goal in natural language, and a coding agent generates:
- the node graph  
- the connection logic  
- validation tests  

This shifts development from manually designing execution paths to defining desired outcomes.

### Adaptive Behavior Instead of Manual Debugging
In many frameworks, failures require manual debugging, code updates, and redeployment.  
Hive captures failure data, evaluates what went wrong relative to the defined goal, and can evolve the agent graph automatically — enabling continuous improvement over time.

### Built-In Control and Observability
Hive is designed for production environments and includes:
- human-in-the-loop checkpoints  
- real-time execution monitoring  
- credential management  
- cost and budget controls  

These capabilities are integrated into the framework rather than added externally.

### Designed for Real Business Processes
Hive is intended for long-running, autonomous agents that operate within guardrails and evolve based on outcomes — not just simple chains or one-off scripts.

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

## Roadmap

Aden Hive Agent Framework aims to help developers build outcome-oriented, self-adaptive agents. See [roadmap.md](docs/roadmap.md) for details.

```mermaid
flowchart TB
    %% Main Entity
    User([User])

    %% =========================================
    %% EXTERNAL EVENT SOURCES
    %% =========================================
    subgraph ExtEventSource [External Event Source]
        E_Sch["Schedulers"]
        E_WH["Webhook"]
        E_SSE["SSE"]
    end

    %% =========================================
    %% SYSTEM NODES
    %% =========================================
    subgraph WorkerBees [Worker Bees]
        WB_C["Conversation"]
        WB_SP["System prompt"]

        subgraph Graph [Graph]
            direction TB
            N1["Node"] --> N2["Node"] --> N3["Node"]
            N1 -.-> AN["Active Node"]
            N2 -.-> AN
            N3 -.-> AN

            %% Nested Event Loop Node
            subgraph EventLoopNode [Event Loop Node]
                ELN_L["listener"]
                ELN_SP["System Prompt<br/>(Task)"]
                ELN_EL["Event loop"]
                ELN_C["Conversation"]
            end
        end
    end

    subgraph JudgeNode [Judge]
        J_C["Criteria"]
        J_P["Principles"]
        J_EL["Event loop"] <--> J_S["Scheduler"]
    end

    subgraph QueenBee [Queen Bee]
        QB_SP["System prompt"]
        QB_EL["Event loop"]
        QB_C["Conversation"]
    end

    subgraph Infra [Infra]
        SA["Sub Agent"]
        TR["Tool Registry"]
        WTM["Write through Conversation Memory<br/>(Logs/RAM/Harddrive)"]
        SM["Shared Memory<br/>(State/Harddrive)"]
        EB["Event Bus<br/>(RAM)"]
        CS["Credential Store<br/>(Harddrive/Cloud)"]
    end

    subgraph PC [PC]
        B["Browser"]
        CB["Codebase<br/>v 0.0.x ... v n.n.n"]
    end

    %% =========================================
    %% CONNECTIONS & DATA FLOW
    %% =========================================

    %% External Event Routing
    E_Sch --> ELN_L
    E_WH --> ELN_L
    E_SSE --> ELN_L
    ELN_L -->|"triggers"| ELN_EL

    %% User Interactions
    User -->|"Talk"| WB_C
    User -->|"Talk"| QB_C
    User -->|"Read/Write Access"| CS

    %% Inter-System Logic
    ELN_C <-->|"Mirror"| WB_C
    WB_C -->|"Focus"| AN

    WorkerBees -->|"Inquire"| JudgeNode
    JudgeNode -->|"Approve"| WorkerBees

    %% Judge Alignments
    J_C <-.->|"aligns"| WB_SP
    J_P <-.->|"aligns"| QB_SP

    %% Escalate path
    J_EL -->|"Report (Escalate)"| QB_EL

    %% Pub/Sub Logic
    AN -->|"publish"| EB
    EB -->|"subscribe"| QB_C

    %% Infra and Process Spawning
    ELN_EL -->|"Spawn"| SA
    SA -->|"Inform"| ELN_EL
    SA -->|"Starts"| B
    B -->|"Report"| ELN_EL
    TR -->|"Assigned"| ELN_EL
    CB -->|"Modify Worker Bee"| WB_C

    %% =========================================
    %% SHARED MEMORY & LOGS ACCESS
    %% =========================================

    %% Worker Bees Access (link to node inside Graph subgraph)
    AN <-->|"Read/Write"| WTM
    AN <-->|"Read/Write"| SM

    %% Queen Bee Access
    QB_C <-->|"Read/Write"| WTM
    QB_EL <-->|"Read/Write"| SM

    %% Credentials Access
    CS -->|"Read Access"| QB_C
```

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
