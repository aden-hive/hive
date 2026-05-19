# Developer success
Our value and principle is developer success. We truly care about helping developers achieve their goals — not just shipping features, but ensuring every developer who uses Hive can build, debug, deploy, and iterate on agents that work in production. Developer success means our developers succeed in their own work: automating real business processes, shipping products, and growing their capabilities. If our developers aren't winning, we aren't winning.

## Developer profiles
From what we currently see, these are the developers who will achieve success with our framework the earliest with our framework
- IT Specialists and Consultants
- Individual developers who want to build a product
- Developers who want to get a job done (they have a real-world business process)
- Developers Who Want to learn and become a business process owner
- One-man CEOs

## How They Find Us & Why They Use Us

**IT Specialists and Consultants:**
Always trying to learn and find the state-of-the-art tools on the market, as it defines their career. They tried Claude but found it hard to apply to their customers' needs. They received Vincent's email and wanted to give it a try. They see the opportunity to resell this product and become active users of ours.

**Developers Who Want to Get a Job Done:**
They find us through our marketing efforts selling the sample agents and our SEO pages for business processes, while they're researching solutions to the problems they're trying to solve.

**Developers Who Want to learn and become a business process owner:** 
They find us through the rage-bait post "If you're a developer that doesn't own a business process, you'll lose your job" and the seminars we host. They believe they need to upgrade themselves from just a coder to somebody who can own a process. They check the GitHub and find the templates interesting. Then they join our Discord to discover more agent ideas developed by the community.

**One-Man CEO:**
Has a business idea and might have some traction, but is overwhelmed by too much work. They saw news saying AI agents can handle all their repetitive tasks. During research, they found us and our tutorials. After seeing a wall of sample agents and playing with them, they couldn't refuse the value and joined our Discord. [See roadmap — Hosted sample agent playgrounds]

**Individual Product Developer:**
Has a product idea and is trying to find the best framework. They encounter a post from Patrick: "I built an AI agent that does market research for me every day using this new framework." They go to our GitHub, find the idea aligned with their vision, and join our Discord.

> **Note:** Individual product developers want to do one thing well and resell it. One-man CEOs have many things to do and need multiple agents.

> **Note:** Ordered by importance. Here is the rationale: Among all developers, IT people are going to be the first group to truly deploy their work in production and achieve real developer success. They are also likely to contribute to the framework. Developers who want to learn are the group who won't get things deployed anytime soon but can be good community members. The product developer is the more long-term play. As a dev tool, it would be a huge developer success if we have them building a product with it. It is the hardest challenge for our framework and also requires good product developers to spend time figuring things out. This is not going to happen in two months.

## What Is Their Success

**IT Specialists and Consultants:**
Success means they're able to resell our framework to their customers and deliver use cases in a production environment. It will be critical for us to have a few "less serious" use cases so people know where to start.

**Developers Who Want to Get a Job Done:**
The framework is adjustable enough for developers to either start from scratch or build from templates to get the job done.

Job done is considered as:
1. The developer deploys it to production and gets users to use it
2. The developer starts to own the business process and knows how to maintain it
3. The developer can add more features and integrations to expand the agent's capability as the business process updates
4. The developer is alerted when any failure/escalation happens and is able to debug the agent when sessions go wrong

**Developers Who Want to Learn and Become a Business Process Owner:**
1. The developer learns from sample agents how business processes are done
2. The developer can deploy a sample agent for their team to automate some processes
3. The developer starts to own the business process and knows how to maintain it
4. The developer can add more features and integrations to expand the agent's capability as the business process updates
5. The developer is able to debug the agent when sessions go wrong

**One-Man CEO:**
1. The developer can deploy multiple agents from sample agents
2. The developer can tweak the agent according to their needs
3. The developer can easily program a human-in-the-loop fallback so when the agent can't handle a problem, they receive a notification and fix the issue themselves
4. The developer can generate ad-hoc agents that solve new issues for their business
5. The developer can turn an ad-hoc agent into an agent that runs repeatedly
6. The developer can turn a repeatedly-running agent into one that runs autonomously
7. When the agent fails, the developer receives an alert

**Individual Product Developer:**
1. The developer can develop an MVP with our generation framework
2. The developer can easily add more capabilities
3. The developer can trust the framework is future-proof for them
4. The developer can have a deployment strategy where they wrap the agent as part of their product
5. The developer can monitor the logs and costs for their users
6. The product achieves success (like Unity), long term

```
**Summary:**
The common denominator:
1. Can create an agent
2. Can debug the agent
3. Can maintain the agent
4. Can deploy the agent
5. Can iterate on the agent
```

## Basic use cases (we shall have template for each one of these)

- Github issue triaging agent
- Tech&AI news digest agent
- Research report agent
- Teams daily digest and to-dos
- Discord autoreply bot
- Finance stock digest
- WhatsApp auto response agent
- Email followup agent
- Meeting time coordination agent

## Intermediate use cases

### 1. Sales & Marketing
Marketing is often the most time-consuming "distraction" for a CEO. You provide the vision; they provide the volume.

- [Social Media Management](../examples/recipes/social_media_management/): Scheduling posts, replying to comments, and monitoring trends.
- [News Jacking](../examples/recipes/news_jacking/): Personalized outreach triggered by real-time company news (funding, hires, press mentions).
- [Newsletter Production](../examples/recipes/newsletter_production/): Taking your raw ideas or voice memos and turning them into a polished weekly email.
- [CRM Update Agent](../examples/recipes/crm_hygiene/): Ensuring every lead has a follow-up date and a status update.

### 2. Customer Success
You shouldn't be the one answering "How do I reset my password?" but you should be the one closing $10k deals.

- [Inquiry Triaging](../examples/recipes/inquiry_triaging/): Sorting the "tire kickers" from the "hot leads."
- [Onboarding Assistance](../examples/recipes/onboarding_assistance/): Helping new clients set up their accounts or sending out "Welcome" kits.
- [Customer support & Troubleshooting](../examples/recipes/support_troubleshooting/): Handling "Level 1" tech support for your platform or website.

### 3. Operations Automation
This is your right hand. They keep the gears greased so you don't get stuck in the "admin trap."

- [Email Inbox Management](../examples/recipes/inbox_management/): Clearing out the spam and highlighting the three emails that actually need your brain.
- [Invoicing & Collections](../examples/recipes/invoicing_collections/): Sending out bills and—more importantly—politely chasing down the people who haven't paid them.
- [Data Keeper](../examples/recipes/data_keeper/): Pull data and reports from multiple data sources, and union them in one place.
- [Travel & Calendar Coordination](../examples/recipes/calendar_coordination/): Protecting your "Deep Work" time from getting fragmented by random 15-minute meetings.

### 4. The Technical & Product Maintenance
Unless you are a developer, tech debt will kill your productivity. A part-timer can keep the lights on.

- [Quality Assurance](../examples/recipes/quality_assurance/): Testing new features or links before they go live to ensure nothing is broken.
- [Documentation](../examples/recipes/documentation/): Turning your messy processes into clean Standard Operating Procedures (SOPs).
- [Issue Triaging](../examples/recipes/issue_triaging/): Categorizing and routing incoming bug reports by severity.

## Installation

Install the prerequisites like Python, then install the quickstart package.

## Use Existing Agent

To run an existing agent:

1. Run `hive run <agent_name>` or `hive tui <agent_name>`
2. Hive automatically validates that your agent has all required prerequisites
3. Type something in the TUI or trigger an event source (like receiving an email)
4. Your agent runs, and the outcome is recorded
5. If something fails, you'll see where the logs are saved

## Agent Generation (Alternative to Using Existing Agent)

If you want to build something custom, you can generate your own agent from scratch. See [Agent Generation](#agent-generation).

If you prefer to start with a working example first, try running an existing agent to see how it works. See [Use Existing Agent](#use-existing-agent).

If you find something you can't accomplish with the framework, you can contribute by opening an issue or sharing your feedback in our Discord channel.

## Agent Testing

**Interactive testing:** Run `hive tui` to test your agent in a terminal UI.

**Autonomous testing:** Run `hive run <agent_name> --debug` and trigger the event source. Testing scheduled events can be tricky—Hive provides developer tools to help you simulate them.

**Try before you install:** You can test sample agents hosted in the cloud without any local installation.

## Integration

You need to set up integrations correctly before testing can succeed.

**Happy path:** Your agent accomplishes the goal exactly as specified.

**Mid path:** After negotiation, your agent explicitly tells you what it can and cannot do.

**Sad path:** After negotiation, you may need to build a one-off integration for certain tools.

## Agent Debugging

When errors or unexpected behavior happen during testing, you need to be able to debug your agent effectively.

## Logging

Hive gives you an AI-assisted experience for checking logs and getting high signal-to-noise insights.

Hive uses **three-level observability** for tracking agent execution:

| Level | What it captures | File |
|-------|------------------|------|
| **L1 (Summary)** | Run outcomes — success/failure, execution quality, attention flags | `summary.json` |
| **L2 (Details)** | Per-node results — retries, verdicts, latency, attention reasons | `details.jsonl` |
| **L3 (Tool Logs)** | Step-by-step execution — tool calls, LLM responses, judge feedback | `tool_logs.jsonl` |

## (Optional) How Graph Works

To fix and improve your agent, you need to understand how node memory works and how tools are called. See `docs/key_concepts` for details.

## **First Success**

By this point, you should have run your first agent and understand how the framework works. You're ready to use it for real use cases, which often means updating and customizing your agent.

Everything before your first success should run as smoothly as possible—this is non-negotiable.

## Contribution

If you encounter issues creating your desired agent, or find that the integrations aren't sufficient for your use case, open an issue or let us know in our Discord channel.

## Iteration (Building) - More Like Debugging

After your MVP agent or sample agent runs, you'll want to iterate by expanding the use cases.

## Iteration (Production) - Evolution and Inventiveness

After your MVP is deployed, your taste and judgment still drive the direction—AI is a significant force multiplier for rapidly iterating and solving problems.

With Aden Cloud Hive, production evolution is fully automatic. The Aden Queen Bee runs natural selection by deploying, evaluating, and improving your agents.

## Version Control

Iteration doesn't always improve everything. Version control helps you get back to a previous version, like how git works. Run `hive git restore` to revert changes.

## Agent Personality

You can put your own soul into your agent. What remains constant across evolution matters. Success isn't about having your agent constantly changing—it's about knowing that your goal and personality stay fixed while your agent adapts to solve problems.

## Memory Management

Hive nodes have a built-in mechanism for handling node memory and passing memory between nodes. To implement cross-session memory or custom memory logic, use the memory tools.

# Deployment

## (Optional) How Agent Runtime Works

To fix and improve your agent, you need to understand how data transfers during runtime, how memory works, and how tools work. See `./agent_runtime.md` for details.

## Local Deployment

By default, Hive supports deployment through Docker.

1. Pre-flight Validation (Critical)
2. One-Command Deployment (`hive deploy local my_agent`)
3. Credential Handling in Containers (local credentials + Aden Cloud Credentials for OAuth)
4. Persistence & State
5. Debugging/Logging/Memory Access (start with CLI commands)
6. Expose Hooks and APIs as SDK
7. Documentation Deliverables

## Cloud Deployment

If you want zero-ops deployment, easier integration and credential management, and built-in logging, Aden Cloud is ideal. You get secure defaults, scaling, and observability out of the box—at the cost of less low-level control and some vendor lock-in.

## Autonomous Agent Deployment

Hive is designed to support 

- Memory sustainalibility (what are the memory to keep and what to discard)
- Event source management
- Recoverablility
- Repeatability
- Volume - Multiple approach to support batch operation


## Deployment Strategy

Autonomous and interactive modes look different, but the core remains the same, and your deployment strategy should be consistent across both.

## Performance

Not a focus at the moment. Speed of execution, process pools, and hallucination handling are future considerations.

## How We Collect Data

Self-reported issues and cloud observability products.

## Runtime Guardrails

Hive provides built-in safety mechanisms to keep your agents within bounds.

## How We Make Reliability

Breakages still happen, even in the best business processes. Being reliable means being adaptive and fixing problems when they arise.

## Developer Trust

To deploy your agent for production use, Hive provides transparency in runtime, sufficient control, and guardrails to avoid catastrophic results.
