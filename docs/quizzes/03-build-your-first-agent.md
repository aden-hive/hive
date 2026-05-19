# 🤖 Build Your First Agent Challenge

Get hands-on with AI agents! This challenge is for AI/ML engineers who want to understand agent development and contribute to Aden's agent ecosystem.

**Difficulty:** Intermediate
**Time:** 2-3 hours
**Prerequisites:** Complete [Getting Started](./01-getting-started.md), Python experience, basic LLM knowledge

---

## Part 1: Agent Fundamentals (20 points)

### Task 1.1: Core Concepts 📚
Answer these questions about Aden's agent architecture:

1. What is a "node" in Aden's architecture? How does it differ from a traditional function?

2. Explain the SDK-wrapped node concept. What four capabilities does every node get automatically?

3. What's the difference between:
   - A Coding Agent and a Worker Agent
   - Goal-driven vs workflow-driven development
   - Predefined edges vs dynamic connections

4. Why does Aden generate "connection code" instead of using a fixed graph structure?

### Task 1.2: Memory Systems 🧠
Aden has sophisticated memory management:

1. Describe the three types of memory available to agents:
   - Shared Memory
   - STM (Short-Term Memory)
   - LTM (Long-Term Memory / RLM)

2. When would an agent use each type?

3. How does "Session Local memory isolation" work?

### Task 1.3: Human-in-the-Loop 🙋
Explain the HITL system:

1. What triggers a human intervention point?
2. What happens if a human doesn't respond within the timeout?
3. List three scenarios where HITL would be essential

---

## Part 2: Agent Design (25 points)

### Task 2.1: Design a Multi-Agent System 🎭
Design a **Content Marketing Agent System** with multiple worker agents:

**Goal:** Automatically create and publish blog posts based on company news

Requirements:
- Must use at least 3 specialized worker agents
- Include human approval before publishing
- Handle failures gracefully

Provide:
1. **Agent Diagram:** Show all agents and how they connect
2. **Agent Descriptions:** For each agent, describe:
   - Name and role
   - Inputs and outputs
   - Tools it needs
   - Failure scenarios
3. **Human Checkpoints:** Where would humans intervene?
4. **Self-Improvement:** How would this system learn from failures?

### Task 2.2: Goal Definition 🎯
Write a natural language goal that a user might give to create your system:

```
Example Goal:
"Create a system that monitors our company RSS feed for news,
writes engaging blog posts about each news item, gets approval
from the marketing team, and publishes to our WordPress site.
If a post is rejected, learn from the feedback to write better
posts in the future."
```

Your goal should be:
- Clear and specific
- Include success criteria
- Mention failure handling
- Specify human touchpoints

### Task 2.3: Test Cases 📋
Design 5 test cases for your agent system:

| Test Case | Input | Expected Output | Success Criteria |
|-----------|-------|-----------------|------------------|
| Happy Path | Normal news item | Published blog post | Post live on site |
| ... | ... | ... | ... |

Include at least:
- 1 happy path
- 2 edge cases
- 2 failure scenarios

---

## Part 3: Practical Implementation (30 points)

### Task 3.1: Agent Pseudocode 💻
Write pseudocode for ONE of your worker agents:

```python
class ContentWriterAgent:
    """
    Agent that takes news items and writes blog posts.
    """

    def __init__(self, config):
        # Initialize with tools, memory, LLM access
        pass

    async def execute(self, input_data):
        # Main execution logic
        pass

    async def handle_failure(self, error, context):
        # How to handle different types of failures
        pass

    async def learn_from_feedback(self, feedback):
        # How to improve based on rejection feedback
        pass
```

Provide detailed pseudocode with:
- LLM calls and prompts
- Memory reads/writes
- Tool usage
- Error handling

### Task 3.2: Prompt Engineering 📝
Write the actual prompts for your agent:

1. **System Prompt:** The core instructions for your agent
2. **Task Prompt Template:** How tasks are presented to the agent
3. **Feedback Learning Prompt:** How rejection feedback is processed

Example format:
```
SYSTEM PROMPT:
You are a professional content writer for {company_name}...

TASK PROMPT:
Given the following news item:
{news_content}

Write a blog post that...

FEEDBACK PROMPT:
Your previous post was rejected with this feedback:
{feedback}

Analyze what went wrong and...
```

### Task 3.3: Tool Definitions 🔧
Define the tools your agent needs:

```python
tools = [
    {
        "name": "search_company_knowledge",
        "description": "Search internal knowledge base for relevant context",
        "parameters": {
            "query": "string - search query",
            "limit": "int - max results (default 5)"
        },
        "returns": "List of relevant documents"
    },
    # Add more tools...
]
```

Define at least 3 tools with:
- Clear name and description
- Input parameters with types
- Return value description
- Example usage

---

## Part 4: Advanced Challenges (25 points)

### Task 4.1: Failure Evolution Design 🔄
Design the self-improvement mechanism in detail:

1. **Failure Classification:** Create a taxonomy of failures for your agent
   ```
   - LLM Failures: rate limit, content filter, hallucination
   - Tool Failures: API down, invalid response, timeout
   - Logic Failures: wrong output format, missing data
   - Human Rejection: quality issues, off-brand, factual error
   ```

2. **Learning Storage:** What data do you store for each failure type?

3. **Evolution Strategy:** How does the Coding Agent use failure data to improve?

4. **Guardrails:** What prevents the system from making things worse?

### Task 4.2: Cost Optimization 💰
Your agent system will be called frequently. Design cost optimizations:

1. **Model Selection:** When to use GPT-4 vs GPT-3.5 vs Claude Haiku?
2. **Caching Strategy:** What can be cached to reduce LLM calls?
3. **Batching:** How can you batch operations for efficiency?
4. **Budget Rules:** Design budget rules for your system

### Task 4.3: Observability Dashboard 📊
Design what metrics should be tracked for your agent system:

1. **Performance Metrics:** (at least 5)
2. **Quality Metrics:** (at least 3)
3. **Cost Metrics:** (at least 3)
4. **Alert Conditions:** When should the system alert humans?

---

## Submission Checklist

- [ ] All Part 1 concept answers
- [ ] Complete multi-agent design (Part 2)
- [ ] Implementation code/pseudocode (Part 3)
- [ ] Advanced challenge solutions (Part 4)

### How to Submit

1. Create a GitHub Gist with your answers
2. Name it `aden-agent-challenge-YOURNAME.md`
3. Include code files separately
4. If you created diagrams, include images
5. Email to `careers@adenhq.com`
   - Subject: `[Agent Challenge] Your Name`

---

## Scoring

| Section | Points |
|---------|--------|
| Part 1: Fundamentals | 20 |
| Part 2: Design | 25 |
| Part 3: Implementation | 30 |
| Part 4: Advanced | 25 |
| **Total** | **100** |

**Passing score:** 75+ points

---

## Bonus Points (+25)

- **+10:** Actually implement a working prototype using any framework
- **+10:** Create a demo video of your agent in action
- **+5:** Submit a PR adding your agent as a template to the repo

---

## Example Agent Templates

Need inspiration? Here are some agent ideas:

1. **Research Agent:** Gathers information from multiple sources
2. **Code Review Agent:** Reviews PRs and suggests improvements
3. **Customer Support Agent:** Handles support tickets with escalation
4. **Data Pipeline Agent:** Monitors and fixes data quality issues
5. **Meeting Agent:** Summarizes meetings and creates action items

---

Good luck! We're excited to see your creative agent designs! 🤖✨
