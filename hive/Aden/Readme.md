# Content Marketing Agent Template

A production-ready multi-agent system for autonomous content creation and publishing using LangChain and OpenAI.

## Features

- **4 Specialized Agents**
  - Content Writer: Generates engaging blog posts from news items
  - Fact Checker: Validates factual accuracy
  - Marketing Reviewer: Ensures brand compliance
  - Publisher: Handles publishing workflow

- **Memory System** (Aden Architecture)
  - Shared Memory: Workspace configuration and guidelines
  - STM (Short-Term Memory): Session-isolated working memory
  - LTM (Long-Term Memory): Persistent learnings for self-improvement

- **Session Isolation**: Each execution gets isolated memory
- **Error Handling**: Graceful fallbacks for API failures
- **Event Logging**: Complete workflow tracking
- **Self-Improving**: Accumulates learnings in LTM

## Quick Start

### Prerequisites
```bash
pip install langchain langchain-openai langchain-core openai pydantic
```

### Setup
```bash
export OPENAI_API_KEY="sk-your-api-key-here"
```

### Run
```bash
python agent.py
```

## Expected Output