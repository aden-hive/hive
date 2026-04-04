# Research + Summary Agent

This is a complete, multi-step agent built using the Hive (Aden) framework. It demonstrates how to perform information processing by gathering data, extracting key insights, and generating a structured summary.

## Flow / Agent Graph

1. **Information Gathering (`gather_info`)**: Uses web search and scraping tools to look up the provided query and assemble raw data.
2. **Key Point Extraction (`extract_points`)**: An analytical step that processes the raw text without web access to find the most important trends and notable tools.
3. **Summarization (`summarize`)**: Acts as a technical writer, taking the original query and the extracted points to generate a final markdown summary.

## How to Run

Make sure your environment is activated and your LLM API keys are set (e.g., `OPENAI_API_KEY`). By default, the framework uses `gpt-4o-mini`.

Run the agent via the CLI:
```bash
python -m examples.research_agent run --query "Latest trends in AI agents"
```

To see more verbosity (logs of what the agent is doing):
```bash
python -m examples.research_agent run --query "Latest trends in AI agents" -v
```

See information about the agent's graph:
```bash
python -m examples.research_agent info
```

## Example Input / Output

**Input Query:**
"Latest trends in AI agents"

**Example Output:**
```markdown
--- SUMMARY ---

# AI Agents: Latest Trends

The landscape of AI agents is evolving rapidly, moving from single-turn chat interfaces to autonomous, multi-step systems capable of complex reasoning.

**Key Trends:**
* Multi-Agent Systems: Systems now frequently use specialized sub-agents coordinating to solve complex tasks.
* Edge and Local Execution: Pushing smaller, efficient models to run locally.
* Tool Integration: Enhanced ability to natively interact with APIs and browser environments.
* Memory Improvements: Extended context windows and long-term storage mechanisms.

**Notable Tools / Technologies:**
* LangChain & AutoGen
* Tool Call/Function Calling APIs
* Browser use integrations

## Conclusion
As agents become more capable of orchestrating complex workflows independently, developers are focusing heavily on reliability, orchestration, and seamless tool usage.
-----------------
```
