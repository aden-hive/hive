# Evolution

## Evolution Is the Mechanism; Adaptiveness Is the Result

Agents don't just fail; they fail inevitably. Real-world variables—private LinkedIn profiles, shifting API schemas, or LLM hallucinations—are impossible to predict in a vacuum. The first version of any agent is merely a "happy path" draft.

Evolution is how Hive handles this. When an agent fails, the framework captures what went wrong — which node failed, which success criteria weren't met, what the agent tried and why it didn't work. Then a coding agent (Claude Code, Cursor, or similar) uses that failure data to generate an improved version of the agent. The new version gets deployed, runs, encounters new edge cases, and the cycle continues.

Over generations, the agent gets more reliable. Not because someone sat down and anticipated every possible failure, but because each failure teaches the next version something specific.

## How It Works

The evolution loop has four stages:

**1. Execute** — The worker agent runs against real inputs. Sessions produce outcomes, decisions, and metrics.

**2. Evaluate** — The framework checks outcomes against the goal's success criteria and constraints. Did the agent produce the desired result? Which criteria were satisfied and which weren't? Were any constraints violated?

**3. Diagnose** — Failure data is structured and specific. It's not just "the agent failed" — it's "node `draft_message` failed to produce personalized content because the research node returned insufficient data about the prospect's recent activity." The decision log, problem reports, and execution trace provide the full picture.

**4. Regenerate** — A coding agent receives the diagnosis and the current agent code. It modifies the graph — adding nodes, adjusting prompts, changing edge conditions, adding tools — to address the specific failure. The new version is deployed and the cycle restarts.

## Adaptiveness ≠ Intelligence or Intent

An important distinction: evolution makes agents more adaptive, but not more intelligent in any general sense. The agent isn't learning to reason better — it's being rewritten to handle more situations correctly.

This is closer to how biological evolution works than how learning works. A species doesn't "learn" to survive winter — individuals that happen to have thicker fur survive, and that trait gets selected for. Similarly, agent versions that handle more edge cases correctly survive in production, and the patterns that made them successful get carried forward.

The practical implication: don't expect evolution to make an agent smarter about problems it's never seen. Evolution improves reliability on the *kinds* of problems the agent has already encountered. For genuinely novel situations, that's what human-in-the-loop is for — and every time a human steps in, that interaction becomes potential fuel for the next evolution cycle.

## What Gets Evolved

Evolution can change almost anything about an agent:

**Prompts** — The most common fix. A node's system prompt gets refined based on the specific ways the LLM misunderstood its instructions.

**Graph structure** — Adding a validation node before a critical step, splitting a node that's trying to do too much, adding a fallback path for a common failure mode.

**Edge conditions** — Adjusting routing logic based on observed patterns. If low-confidence research results consistently lead to bad drafts, add a conditional edge that routes them back for another research pass.

**Tool selection** — Swapping in a better tool, adding a new one, or removing one that causes more problems than it solves.

**Constraints and criteria** — Tightening or loosening based on what's actually achievable and what matters in practice.

## The Role of Decision Logging

Evolution depends on good data. The runtime captures every decision an agent makes: what it was trying to do, what options it considered, what it chose, and what happened as a result. This isn't overhead — it's the signal that makes evolution possible.

Without decision logging, failure analysis is guesswork. With it, the coding agent can trace a failure back to its root cause and make a targeted fix rather than a blind change.