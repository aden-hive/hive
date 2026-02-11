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
- [Newsletter Production](../examples/recipes/newsletter_production/): Taking your raw ideas or voice memos and turning them into a polished weekly email.
- [Ad Campaign Monitoring](../examples/recipes/ad_campaign_monitoring/): Checking daily spends on Meta/Google ads and flagging if the Cost Per Acquisition (CPA) spikes.
- [CRM Update Agent](../examples/recipes/crm_hygiene/): Ensuring every lead has a follow-up date and a status update.

### 2. Customer Success
You shouldn't be the one answering "How do I reset my password?" but you should be the one closing $10k deals.

- [Inquiry Triaging](../examples/recipes/inquiry_triaging/): Sorting the "tire kickers" from the "hot leads."
- [Onboarding Assistance](../examples/recipes/onboarding_assistance/): Helping new clients set up their accounts or sending out "Welcome" kits.

### 3. Operations Automation
This is your right hand. They keep the gears greased so you don't get stuck in the "admin trap."

- [Inbox Management](../examples/recipes/inbox_management/): Clearing out the spam and highlighting the three emails that actually need your brain.
- [Invoicing & Collections](../examples/recipes/invoicing_collections/): Sending out bills and—more importantly—politely chasing down the people who haven't paid them.
- [Data Keeper](../examples/recipes/data_keeper/): Pull data and reports from multiple data sources, and union them in one place.
- [Travel & Calendar Coordination](../examples/recipes/calendar_coordination/): Protecting your "Deep Work" time from getting fragmented by random 15-minute meetings.

### 4. The Technical & Product Maintenance
Unless you are a developer, tech debt will kill your productivity. A part-timer can keep the lights on.

- [Quality Assurance](../examples/recipes/quality_assurance/): Testing new features or links before they go live to ensure nothing is broken.
- [Documentation](../examples/recipes/documentation/): Turning your messy processes into clean Standard Operating Procedures (SOPs).
- [Basic Troubleshooting](../examples/recipes/basic_troubleshooting/): Handling "Level 1" tech support for your platform or website.
- [Issue Triaging](../examples/recipes/issue_triaging/): Categorizing and routing incoming bug reports by severity.

## Installation

Install the prer-requisites like python
Install quickstart

## use existing agent
If user would like to 

These are what happen:
(User) Hive run xxxx / Hive tui xxxx
(automatically) A quick, engineering validation check on if the agent has all the pre-requisits
(User) Type something in the TUI or trigger event source (like email received)
(automatically) Agent run, outcome happens and is recorded
(if failed) Tell the user where the logs are saved

## Agent generation (alternative to using existing agent)

For "Developers who want to get a job done" and the "Individual product developer," they will likely want to try generating the agent themselves. see [## agent generation]

For others, they will likely want to try existing agents first to see how well the agent can work. see [## use existing agent]

If user find somethign they can't fulfill with the framework, they can choose to contribute by share it in an issue or in the discord channel 

## Agent Testing

Interactive testing: Run `hive tui` and test the agent in a tui

Autonomous testing: Run `hive run XXX --debug` and trigger the event source. Testing events, especially the scheduled event can be hard. It would be benificial if we provide some developer tools to finish them.

(after commercial ready stage) Sample agent testing without installation: We host some sample agents on cloud and provide them to the users to test directly without installation

## Integration
Users can't even finish testing without setting up the integration correctly.

Happy path: In the goal setting, the agent do the job super well

mid path: After negotiation, the agent explicitly told the user

Sad path: After negotiation and tried to build a one off integration for certain tools

## Agent Debugging
If any error / unexpected behavior happens during testing, the developer need to be able to debug the agent

## Logging

To make it easier for user to have a AI-assisted experience checking log and get reported the insight with high signal/noise ratio,

Hive uses a **three-level observability** for tracking agent execution:

| Level | What it captures | File |
|-------|------------------|------|
| **L1 (Summary)** | Run outcomes — success/failure, execution quality, attention flags | `summary.json` |
| **L2 (Details)** | Per-node results — retries, verdicts, latency, attention reasons | `details.jsonl` |
| **L3 (Tool Logs)** | Step-by-step execution — tool calls, LLM responses, judge feedback | `tool_logs.jsonl` |

## (Optional) How graph works
Developers need to understand node memory works, how tools are called. for them to fix and improve the agent they built.  see `docs/key_concepts` for details

## **first success**
By here, the developer should already finish running one of their first agent and get a grasp of how the agent frameworks works. They can very well trying to use it for the real use cases, which often invoice updating the current agennt

Anything before the first success is not negotiateble something we need to ensure running as smooth as possible

## Iteration (building) - More like debugging

After the MVP agent/sample agent runs. Developer want to iterate the agent by biggering the use cases. 

## Iteration (production) - Evolution and inventiveness

Afterthe MVP is deployed. Which taste and judgement are still came from the human developers, AI was a significen force multiplier for rapidly iterating and solving problems.

For Aden cloud hive, the production evolution is fully automatic. Aden queen bee run a natural selection by deploying,  evaluating and improving. 

## Version Control

Iteration is not always improving everything. To help the developers, version control helps them getting back to the previous version , ike how git works. They run this command `hive git restore` to to 

## Agent Personality
Developers want to put their own soul into the agent. What remain the same across the evolution is important. Developer success is not about having the agent constantly changing. It is about you know the goal and the personality of the agent will not chanage, and it just adapt to the environment to solve problems.

# Deployment

## (Optional) How agent runtime works
Developers need to understand how data are transfered during agent runtime, how memory works, how tools works. for them to fix and improve the agent they built.  see ./agent_runtime.md for details

## Local Deployment
By default we support deployment through docker. 

## Cloud Deployment
For users who want zero-ops deployment, easier integration and credential management, and logging, Aden cloud is ideal. Users who don’t want to manage infra get secure defaults, scaling, and observability out of the box—at the cost of less low-level control and some vendor lock-in.

## Deployment Strategy
Autonomous and interactive modes look different, but the core should remain the same, and the deployment strategy should also be consistent.

## Performance
Not a focus at the moment
Speed of run, hellucination

## How we collect data
Self-reported issues
Cloud observabiltiy product

## Runtime guardrails

[To be complete]

## How we make reliability

Breakages still happens, even in the most best business process: Being reliable is to be adaptive and fix the problems 

[To be complete]


## Developer trust

[To be complete]
