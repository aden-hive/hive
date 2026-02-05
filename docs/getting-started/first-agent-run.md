# Your First Agent Run: A Complete Walkthrough

This guide walks you through creating and running your first Hive agent from scratch. You'll see exactly what success looks like at each step.

## Prerequisites

Before starting, ensure you've completed the initial setup:

```bash
# Run quickstart (if you haven't already)
./quickstart.sh

# Verify installation
uv run python -c "import framework; import aden_tools; print('✓ Ready')"
```

You should see: `✓ Ready`

## Overview: What We're Building

We'll create a **Research Agent** that:
1. Takes a topic as input
2. Searches the web for information
3. Summarizes findings
4. Returns a structured report

**Time to complete:** ~10 minutes

## Step 1: Start the Agent Builder

Open Claude Code in your Hive directory:

```bash
cd /path/to/hive
claude
```

In Claude Code, invoke the agent building skill:

```
/building-agents-construction
```

You'll see Claude load the agent builder and ask what kind of agent you want to create.

## Step 2: Define Your Goal

When prompted, describe your agent goal:

```
I want to build a research agent that takes a topic as input,
searches the web for current information about that topic,
and returns a well-structured summary with key findings.

Success criteria:
- Must find at least 3 relevant sources
- Summary must be 200-500 words
- Must cite all sources with URLs
```

Claude will create a session and start building your agent.

### What happens behind the scenes:
- Creates a new agent session
- Parses your goal into structured format
- Sets up success criteria
- Prepares to generate nodes

## Step 3: Watch the Agent Build

Claude will now:

1. **Create nodes** for your agent:
   ```
   ✓ Node: research_topic (searches web)
   ✓ Node: analyze_results (processes findings)
   ✓ Node: generate_summary (creates report)
   ```

2. **Connect the nodes** with edges:
   ```
   ✓ Edge: START → research_topic
   ✓ Edge: research_topic → analyze_results (on_success)
   ✓ Edge: analyze_results → generate_summary (on_success)
   ```

3. **Configure tools**:
   ```
   ✓ Added web_search tool
   ✓ Added web_scrape tool
   ```

4. **Export the agent**:
   ```
   ✓ Exported to: exports/research_agent/
   ```

You should see output like:

```
Agent exported successfully!
📁 exports/research_agent/
├── agent.json      (Graph specification)
├── tools.py        (MCP tool configuration)
└── README.md       (Usage instructions)
```

## Step 4: Verify the Agent Structure

Check that your agent was created:

```bash
ls -la exports/research_agent/
```

Expected output:
```
-rw-r--r--  agent.json
-rw-r--r--  tools.py
-rw-r--r--  README.md
```

Inspect the agent configuration:

```bash
cat exports/research_agent/agent.json | uv run python -m json.tool | head -20
```

You should see a valid JSON with `graph`, `goal`, and node definitions.

## Step 5: Test the Agent

Now let's run your agent! In Claude Code:

```
/testing-agent
```

When prompted for the agent path:
```
exports/research_agent
```

When prompted for test input:
```json
{
  "topic": "Recent developments in renewable energy"
}
```

### Expected Test Output

You should see:

```
✓ Starting agent test...
✓ Loading agent from exports/research_agent
✓ Agent loaded successfully

Running execution...

[Node: research_topic]
  Tool: web_search("Recent developments in renewable energy")
  Found 5 articles
  ✓ Node completed

[Node: analyze_results]
  Processing 5 sources
  Extracting key points
  ✓ Node completed

[Node: generate_summary]
  Creating summary (342 words)
  Adding citations
  ✓ Node completed

✓ Agent execution successful!

Results:
{
  "summary": "Recent developments in renewable energy...",
  "sources": [
    "https://...",
    "https://...",
    "https://..."
  ],
  "word_count": 342
}

✓ All success criteria met
  ✓ Found 5 sources (target: 3+)
  ✓ Summary length: 342 words (target: 200-500)
  ✓ All sources cited with URLs
```

## Step 6: Run the Agent Manually

You can also run the agent from the command line:

```bash
PYTHONPATH=core:exports uv run python -m research_agent run \
  --input '{"topic": "Recent developments in renewable energy"}'
```

### Understanding the Output

The agent will execute and show:

1. **Node execution log:**
   ```
   [2026-02-05 17:30:00] Starting node: research_topic
   [2026-02-05 17:30:02] Tool call: web_search
   [2026-02-05 17:30:05] Node completed: research_topic
   ```

2. **Final result:**
   ```json
   {
     "status": "success",
     "result": {
       "summary": "...",
       "sources": [...],
       "word_count": 342
     },
     "execution_time": 12.5,
     "nodes_executed": 3
   }
   ```

3. **Success criteria evaluation:**
   ```
   ✓ Found 5 sources (required: 3+)
   ✓ Summary length: 342 words (required: 200-500)
   ✓ All sources cited
   ```

## Step 7: Iterate and Improve

Now try different inputs:

```bash
# Technology topic
PYTHONPATH=core:exports uv run python -m research_agent run \
  --input '{"topic": "Quantum computing breakthroughs 2025"}'

# Science topic
PYTHONPATH=core:exports uv run python -m research_agent run \
  --input '{"topic": "CRISPR gene therapy advances"}'
```

## Troubleshooting

### Issue: "No module named 'research_agent'"

**Solution:**
```bash
# Ensure PYTHONPATH includes both core and exports
export PYTHONPATH=core:exports
uv run python -m research_agent run --input '{...}'
```

### Issue: "Tool 'web_search' not found"

**Solution:**
Check that your API keys are configured:
```bash
# Check for required keys
cat .env | grep -E "ANTHROPIC|OPENAI|TAVILY"

# Add missing keys
echo "TAVILY_API_KEY=your-key" >> .env
```

### Issue: Agent fails with "Success criteria not met"

**Solution:**
This is expected! The agent will evolve:
```
❌ Success criteria not met
   ❌ Found only 2 sources (required: 3+)

→ Triggering evolution...
→ Coding Agent analyzing failure
→ Adding retry logic to research_topic node
→ Redeploying agent

✓ Evolution complete, re-running...
```

## What You've Learned

You now know how to:

✅ Build an agent using Claude Code skills
✅ Define clear goals and success criteria
✅ Test agents in development
✅ Run agents from the command line
✅ Interpret execution logs and results
✅ Understand the evolution process

## Next Steps

### Explore More Complex Agents

Try building:

- **Multi-step workflow:** Add more nodes for complex processing
- **Human-in-the-loop:** Add intervention points for approval
- **Multi-agent coordination:** Have agents call other agents

### Learn Advanced Concepts

- [Self-Evolving Agents](../concepts/self-evolving-agents.md) - How agents improve over time
- [Goal-Driven Development](../concepts/goal-driven-development.md) - Writing effective goals
- [Agent Architecture](../architecture/README.md) - Understanding graphs and nodes

### Build Production Agents

- [Deployment Guide](../deployment/README.md) - Deploy to production
- [Monitoring](../observability/monitoring.md) - Set up observability
- [Cost Control](../cost-control.md) - Manage LLM costs

## Example Agents to Study

Check out example agents in `exports/`:

```bash
# List all example agents
ls -la exports/

# Study a complex example
cat exports/marketing_agent/agent.json | uv run python -m json.tool
```

## Common First Agent Patterns

### Pattern 1: Data Processing Agent
```
Input → Fetch Data → Transform → Validate → Output
```

### Pattern 2: Research & Analysis Agent
```
Input → Search → Filter → Analyze → Summarize → Output
```

### Pattern 3: Communication Agent
```
Input → Draft Message → Review → Send → Confirm → Output
```

### Pattern 4: Decision Agent
```
Input → Gather Info → Evaluate Options → Decide → Execute → Output
```

## Summary

You've successfully:

1. ✅ Created your first agent using `/building-agents-construction`
2. ✅ Defined a clear goal with success criteria
3. ✅ Tested the agent with `/testing-agent`
4. ✅ Ran the agent manually from the command line
5. ✅ Understood the execution flow and output

Your agent is now ready to use, and will evolve over time as it encounters new scenarios!

## Getting Help

- **Discord:** [Join the community](https://discord.com/invite/MXE49hrKDk)
- **Issues:** [Report bugs](https://github.com/adenhq/hive/issues)
- **Docs:** [Full documentation](https://docs.adenhq.com)

---

**Congratulations!** You've completed your first successful agent run. 🎉

Now go build something amazing!
