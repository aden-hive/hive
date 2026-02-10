# Developer success
Our value and principle is developer success. We truly care about helping developers achieve their goals — not just shipping features, but ensuring every developer who uses Hive can build, debug, deploy, and iterate on agents that work in production. Developer success means our developers succeed in their own work: automating real business processes, shipping products, and growing their capabilities. If our developers aren't winning, we aren't winning.

## Developer we're going after

- Individual developers who want to build a product
- Developers who want to get a job done (they have a real-world business process)
- Developers who want to learn how they can level up
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


## Onboarding Experience

For "Developers who want to get a job done" and the "Individual product developer," they will likely want to try generating the agent themselves. see [## agent generation]

For others, they will likely want to try existing agents first to see how well the agent can work. see [## use existing agent]

## Agent Generation

[To be complete]

## Integration

Happy path: In the goal setting, the agent do the job super well

mid path: After negotiation, the agent explicitly told the user

Sad path: After negotiation and tried to build a one off integration for certain tools

## Agent Testing

Interactive testing: 

Autonomous testing: 

## How agent runtime works

## use existing agent
If user would like to 

These are what happen:
(User) Hive run xxxx / Hive tui xxxx
(automatically) A quick, engineering validation check on if the agent has all the pre-requisits
(User) Type something in the TUI or trigger event source (like email received)
(automatically) Agent run, outcome happens and is recorded
(if failed) Tell the user where the logs are saved



## Iteration (building) - More like debugging

[To be complete]


## Iteration (production) - Evolution and inventiveness

[To be complete]

## Automomous
Core should remain the same, different deployment flag

## Performance
Not a focus at the moment
Speed of run, hellucination


## How we collect data
Self-reported issues
Cloud observabiltiy product

## How guardrail is done

[To be complete]

## How we make reliability


Breakages still happens, even in the most best business process: Being reliable is to be adaptive and fix the problems 

[To be complete]


## Developer trust

[To be complete]


## What Success Looks Like for Them

In short, the common ground is having the agent "used in prod."

## Deployment Strategy

How the developers deploy their agents. Autonomous and interactive agent might be different. Human in the loop might need hooks and sdks