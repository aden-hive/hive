<p align="center">
  <img width="100%" alt="Hive Banner" src="https://storage.googleapis.com/aden-prod-assets/website/aden-title-card.png" />
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

[![Apache 2.0 License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://github.com/adenhq/hive/blob/main/LICENSE)
[![Y Combinator](https://img.shields.io/badge/Y%20Combinator-Aden-orange)](https://www.ycombinator.com/companies/aden)
[![Discord](https://img.shields.io/discord/1172610340073242735?logo=discord&labelColor=%235462eb&logoColor=%23f5f5f5&color=%235462eb)](https://discord.com/invite/MXE49hrKDk)
[![Twitter Follow](https://img.shields.io/twitter/follow/teamaden?logo=X&color=%23f5f5f5)](https://x.com/aden_hq)
[![LinkedIn](https://custom-icon-badges.demolab.com/badge/LinkedIn-0A66C2?logo=linkedin-white&logoColor=fff)](https://www.linkedin.com/company/teamaden/)

<p align="center">
  <img src="https://img.shields.io/badge/AI_Agents-Self--Improving-brightgreen?style=flat-square" alt="AI Agents" />
  <img src="https://img.shields.io/badge/Multi--Agent-Systems-blue?style=flat-square" alt="Multi-Agent" />
  <img src="https://img.shields.io/badge/Goal--Driven-Development-purple?style=flat-square" alt="Goal-Driven" />
  <img src="https://img.shields.io/badge/Human--in--the--Loop-orange?style=flat-square" alt="HITL" />
  <img src="https://img.shields.io/badge/Production--Ready-red?style=flat-square" alt="Production" />
</p>
<p align="center">
  <img src="https://img.shields.io/badge/OpenAI-supported-412991?style=flat-square&logo=openai" alt="OpenAI" />
  <img src="https://img.shields.io/badge/Anthropic-supported-d4a574?style=flat-square" alt="Anthropic" />
  <img src="https://img.shields.io/badge/Google_Gemini-supported-4285F4?style=flat-square&logo=google" alt="Gemini" />
  <img src="https://img.shields.io/badge/MCP-19_Tools-00ADD8?style=flat-square" alt="MCP" />
</p>

## Overview

Build reliable, self-improving AI agents without hardcoding workflows. Define your goal through conversation with a coding agent, and the framework generates a node graph with dynamically created connection code. When things break, the framework captures failure data, evolves the agent through the coding agent, and redeploys. Built-in human-in-the-loop nodes, credential management, and real-time monitoring give you control without sacrificing adaptability.

Visit [adenhq.com](https://adenhq.com) for complete documentation, examples, and guides.

## Who Is Hive For?

Hive is designed for developers and teams who want to build **production-grade AI agents** without manually wiring complex workflows.

Hive is a good fit if you:

- Want AI agents that **execute real business processes**, not demos
- Prefer **goal-driven development** over hardcoded workflows
- Need **self-healing and adaptive agents** that improve over time
- Require **human-in-the-loop control**, observability, and cost limits
- Plan to run agents in **production environments**

Hive may not be the best fit if you’re only experimenting with simple agent chains or one-off scripts.

## When Should You Use Hive?

Use Hive when you need:

- Long-running, autonomous agents
- Multi-agent coordination
- Continuous improvement based on failures
- Strong monitoring, safety, and budget controls
- A framework that evolves with your goals


## What is Aden

<p align="center">
  <img width="100%" alt="Aden Architecture" src="docs/assets/aden-architecture-diagram.jpg" />
</p>

Aden is a platform for building, deploying, operating, and adapting AI agents:

- **Build** - A Coding Agent generates specialized Worker Agents (Sales, Marketing, Ops) from natural language goals
- **Deploy** - Headless deployment with CI/CD integration and full API lifecycle management
- **Operate** - Real-time monitoring, observability, and runtime guardrails keep agents reliable
- **Adapt** - Continuous evaluation, supervision, and adaptation ensure agents improve over time
- **Infra** - Shared memory, LLM integrations, tools, and skills power every agent

## Quick Links

- **[Documentation](https://docs.adenhq.com/)** - Complete guides and API reference
- **[Self-Hosting Guide](https://docs.adenhq.com/getting-started/quickstart)** - Deploy Hive on your infrastructure
- **[Changelog](https://github.com/adenhq/hive/releases)** - Latest updates and releases
<!-- - **[Roadmap](https://adenhq.com/roadmap)** - Upcoming features and plans -->
- **[Report Issues](https://github.com/adenhq/hive/issues)** - Bug reports and feature requests

## Quick Start

## Prerequisites

- Python 3.11+ for agent development
- Claude Code or Cursor for utilizing agent skills

> **Note for Windows Users:** It is strongly recommended to use **WSL (Windows Subsystem for Linux)** or **Git Bash** to run this framework. Some core automation scripts may not execute correctly in standard Command Prompt or PowerShell.

### Installation

```bash
# Clone the repository
git clone https://github.com/adenhq/hive.git
cd hive

# Run quickstart setup
./quickstart.sh
```

This sets up:
- **framework** - Core agent runtime and graph executor (in `core/.venv`)
- **aden_tools** - MCP tools for agent capabilities (in `tools/.venv`)
- All required Python dependencies

### Build Your First Agent

```bash
# Build an agent using Claude Code
claude> /building-agents-construction

# Test your agent
claude> /testing-agent

# Run your agent
PYTHONPATH=core:exports python -m your_agent_name run --input '{...}'
```

**[📖 Complete Setup Guide](ENVIRONMENT_SETUP.md)** - Detailed instructions for agent development

### Cursor IDE Support

Skills are also available in Cursor. To enable:

1. Open Command Palette (`Cmd+Shift+P` / `Ctrl+Shift+P`)
2. Run `MCP: Enable` to enable MCP servers
3. Restart Cursor to load the MCP servers from `.cursor/mcp.json`
4. Type `/` in Agent chat and search for skills (e.g., `/building-agents-construction`)

## Features

- **Goal-Driven Development** - Define objectives in natural language; the coding agent generates the agent graph and connection code to achieve them
- **Adaptiveness** - Framework captures failures, calibrates according to the objectives, and evolves the agent graph
- **Dynamic Node Connections** - No predefined edges; connection code is generated by any capable LLM based on your goals
- **SDK-Wrapped Nodes** - Every node gets shared memory, local RLM memory, monitoring, tools, and LLM access out of the box
- **Human-in-the-Loop** - Intervention nodes that pause execution for human input with configurable timeouts and escalation
- **Real-time Observability** - WebSocket streaming for live monitoring of agent execution, decisions, and node-to-node communication
- **Cost & Budget Control** - Set spending limits, throttles, and automatic model degradation policies
- **Production-Ready** - Self-hostable, built for scale and reliability

## Why Aden

Hive focuses on generating agents that run real business processes rather than generic agents. Instead of requiring you to manually design workflows, define agent interactions, and handle failures reactively, Hive flips the paradigm: **you describe outcomes, and the system builds itself**—delivering an outcome-driven, adaptive experience with an easy-to-use set of tools and integrations.

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

### The Aden Advantage

| Traditional Frameworks     | Aden                                   |
| -------------------------- | -------------------------------------- |
| Hardcode agent workflows   | Describe goals in natural language     |
| Manual graph definition    | Auto-generated agent graphs            |
| Reactive error handling    | Outcome-evaluation and adaptiveness               |
| Static tool configurations | Dynamic SDK-wrapped nodes              |
| Separate monitoring setup  | Built-in real-time observability       |
| DIY budget management      | Integrated cost controls & degradation |

### How It Works

1. **Define Your Goal** → Describe what you want to achieve in plain English
2. **Coding Agent Generates** → Creates the agent graph, connection code, and test cases
3. **Workers Execute** → SDK-wrapped nodes run with full observability and tool access
4. **Control Plane Monitors** → Real-time metrics, budget enforcement, policy management
5. **Adaptiveness** → On failure, the system evolves the graph and redeploys automatically

## Run pre-built Agents (Coming Soon)

### Run a sample agent
Aden Hive provides a list of featured agents that you can use and build on top of.

### Run an agent shared by others
Put the agent in `exports/` and run `PYTHONPATH=core:exports python -m your_agent_name run --input '{...}'`


For building and running goal-driven agents with the framework:

```bash
# One-time setup
./quickstart.sh

# This sets up:
# - framework package (core runtime)
# - aden_tools package (MCP tools)
# - All Python dependencies

# Build new agents using Claude Code skills
claude> /building-agents-construction

# Test agents
claude> /testing-agent

# Run agents
PYTHONPATH=core:exports python -m agent_name run --input '{...}'
```

See [ENVIRONMENT_SETUP.md](ENVIRONMENT_SETUP.md) for complete setup instructions.

## Documentation

- **[Developer Guide](DEVELOPER.md)** - Comprehensive guide for developers
- [Getting Started](docs/getting-started.md) - Quick setup instructions
- [Configuration Guide](docs/configuration.md) - All configuration options
- [Architecture Overview](docs/architecture/README.md) - System design and structure

## Roadmap

Aden Hive Agent Framework aims to help developers build outcome-oriented, self-adaptive agents. See [ROADMAP.md](ROADMAP.md) for details.

```mermaid
flowchart TD
subgraph Foundation
    direction LR
    subgraph arch["Architecture"]
        a1["Node-Based Architecture"]:::done
        a2["Python SDK"]:::done
        a3["LLM Integration"]:::done
        a4["Communication Protocol"]:::done
    end
    subgraph ca["Coding Agent"]
        b1["Goal Creation Session"]:::done
        b2["Worker Agent Creation"]
        b3["MCP Tools"]:::done
    end
    subgraph wa["Worker Agent"]
        c1["Human-in-the-Loop"]:::done
        c2["Callback Handlers"]:::done
        c3["Intervention Points"]:::done
        c4["Streaming Interface"]
    end
    subgraph cred["Credentials"]
        d1["Setup Process"]:::done
        d2["Pluggable Sources"]:::done
        d3["Enterprise Secrets"]
        d4["Integration Tools"]:::done
    end
    subgraph tools["Tools"]
        e1["File Use"]:::done
        e2["Memory STM/LTM"]:::done
        e3["Web Search/Scraper"]:::done
        e4["CSV/PDF"]:::done
        e5["Excel/Email"]
    end
    subgraph core["Core"]
        f1["Eval System"]
        f2["Pydantic Validation"]:::done
        f3["Documentation"]:::done
        f4["Adaptiveness"]
        f5["Sample Agents"]
    end
end

subgraph Expansion
    direction LR
    subgraph intel["Intelligence"]
        g1["Guardrails"]
        g2["Streaming Mode"]
        g3["Image Generation"]
        g4["Semantic Search"]
    end
    subgraph mem["Memory Iteration"]
        h1["Message Model & Sessions"]
        h2["Storage Migration"]
        h3["Context Building"]
        h4["Proactive Compaction"]
        h5["Token Tracking"]
    end
    subgraph evt["Event System"]
        i1["Event Bus for Nodes"]
    end
    subgraph cas["Coding Agent Support"]
        j1["Claude Code"]
        j2["Cursor"]
        j3["Opencode"]
        j4["Antigravity"]
    end
    subgraph plat["Platform"]
        k1["JavaScript/TypeScript SDK"]
        k2["Custom Tool Integrator"]
        k3["Windows Support"]
    end
    subgraph dep["Deployment"]
        l1["Self-Hosted"]
        l2["Cloud Services"]
        l3["CI/CD Pipeline"]
    end
    subgraph tmpl["Templates"]
        m1["Sales Agent"]
        m2["Marketing Agent"]
        m3["Analytics Agent"]
        m4["Training Agent"]
        m5["Smart Form Agent"]
    end
end

classDef done fill:#9e9e9e,color:#fff,stroke:#757575
```
## Contributing

We welcome contributions from the community! We’re especially looking for help building tools, integrations, and example agents for the framework ([check #2805](https://github.com/adenhq/hive/issues/2805)). If you’re interested in extending its functionality, this is the perfect place to start. Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

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

**Q: Does Hive depend on LangChain or other agent frameworks?**

No. Hive is built from the ground up with no dependencies on LangChain, CrewAI, or other agent frameworks. The framework is designed to be lean and flexible, generating agent graphs dynamically rather than relying on predefined components.

**Q: What LLM providers does Hive support?**

Hive supports 100+ LLM providers through LiteLLM integration, including OpenAI (GPT-4, GPT-4o), Anthropic (Claude models), Google Gemini, DeepSeek, Mistral, Groq, and many more. Simply set the appropriate API key environment variable and specify the model name.

**Q: Can I use Hive with local AI models like Ollama?**

Yes! Hive supports local models through LiteLLM. Simply use the model name format `ollama/model-name` (e.g., `ollama/llama3`, `ollama/mistral`) and ensure Ollama is running locally.

**Q: What makes Hive different from other agent frameworks?**

Hive generates your entire agent system from natural language goals using a coding agent—you don't hardcode workflows or manually define graphs. When agents fail, the framework automatically captures failure data, evolves the agent graph, and redeploys. This self-improving loop is unique to Aden.

**Q: Is Hive open-source?**

Yes, Hive is fully open-source under the Apache License 2.0. We actively encourage community contributions and collaboration.

**Q: Does Hive collect data from users?**

Hive collects telemetry data for monitoring and observability purposes, including token usage, latency metrics, and cost tracking. Content capture (prompts and responses) is configurable and stored with team-scoped data isolation. All data stays within your infrastructure when self-hosted.

**Q: What deployment options does Hive support?**

Hive supports self-hosted deployments via Python packages. See the [Environment Setup Guide](ENVIRONMENT_SETUP.md) for installation instructions. Cloud deployment options and Kubernetes-ready configurations are on the roadmap.

**Q: Can Hive handle complex, production-scale use cases?**

Yes. Hive is explicitly designed for production environments with features like automatic failure recovery, real-time observability, cost controls, and horizontal scaling support. The framework handles both simple automations and complex multi-agent workflows.

**Q: Does Hive support human-in-the-loop workflows?**

Yes, Hive fully supports human-in-the-loop workflows through intervention nodes that pause execution for human input. These include configurable timeouts and escalation policies, allowing seamless collaboration between human experts and AI agents.

**Q: What monitoring and debugging tools does Hive provide?**

Hive includes comprehensive observability features: real-time WebSocket streaming for live agent execution monitoring, TimescaleDB-powered analytics for cost and performance metrics, health check endpoints for Kubernetes integration, and MCP tools for agent execution, including file operations, web search, data processing, and more.

**Q: What programming languages does Hive support?**

The Hive framework is built in Python. A JavaScript/TypeScript SDK is on the roadmap.

**Q: Can Aden agents interact with external tools and APIs?**

Yes. Aden's SDK-wrapped nodes provide built-in tool access, and the framework supports flexible tool ecosystems. Agents can integrate with external APIs, databases, and services through the node architecture.

**Q: How does cost control work in Hive?**

Hive provides granular budget controls including spending limits, throttles, and automatic model degradation policies. You can set budgets at the team, agent, or workflow level, with real-time cost tracking and alerts.

**Q: Where can I find examples and documentation?**

Visit [docs.adenhq.com](https://docs.adenhq.com/) for complete guides, API reference, and getting started tutorials. The repository also includes documentation in the `docs/` folder and a comprehensive [DEVELOPER.md](DEVELOPER.md) guide.

**Q: How can I contribute to Aden?**

Contributions are welcome! Fork the repository, create your feature branch, implement your changes, and submit a pull request. See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

**Q: When will my team start seeing results from Aden's adaptive agents?**

Aden's adaptation loop begins working from the first execution. When an agent fails, the framework captures the failure data, helping developers evolve the agent graph through the coding agent. How quickly this translates to measurable results depends on the complexity of your use case, the quality of your goal definitions, and the volume of executions generating feedback.

**Q: How does Hive compare to other agent frameworks?**

Hive focuses on generating agents that run real business processes, rather than generic agents. This vision emphasizes outcome-driven design, adaptability, and an easy-to-use set of tools and integrations.

**Q: Does Aden offer enterprise support?**

For enterprise inquiries, contact the Aden team through [adenhq.com](https://adenhq.com) or join our [Discord community](https://discord.com/invite/MXE49hrKDk) for support and discussions.

---

<p align="center">
  Made with 🔥 Passion in San Francisco
</p>
