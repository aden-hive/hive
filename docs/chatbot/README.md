# Aden Documentation Chatbot

A chatbot that answers questions about Aden using indexed documentation from https://docs.adenhq.com/

## Files

```
chatbot/
├── README.md           # This file
├── scraper.py          # Scrape docs.adenhq.com
├── search.py           # Search indexed docs
├── chatbot_demo.py     # Simple chatbot (no LLM)
├── chatbot_llm.py      # LLM-powered chatbot ⭐
└── data/
    └── docs_index.json # Indexed documentation
```

---

## Quick Start

### 1. Scrape Documentation (First Time)

```bash
cd d:\projects\interview\hive\hive
python docs/chatbot/scraper.py
```

### 2. Run Interactive Chatbot

```bash
python docs/chatbot/chatbot_demo.py
```

### 3. Ask Single Question

```bash
python docs/chatbot/chatbot_demo.py "What is Aden?"
```

---

## Example Usage

```
👤 You: What is Aden?
🤖 Bot: **What is Aden?**
Aden is a platform for building goal-driven AI agents...

👤 You: How to get started?
🤖 Bot: **Getting Started**
Clone the repository and run quickstart...
```python
git clone https://github.com/adenhq/hive.git
cd hive && ./quickstart.sh
```

👤 You: Show me agent.json example
🤖 Bot: **Code Examples:**
```json
{
  "graph": {
    "entry_node": "analyze",
    "nodes": [...]
  }
}
```
```

---

## Features

| Command | Description |
|---------|-------------|
| `What is Aden?` | Get introduction |
| `How to start?` | Get quickstart guide |
| `Show code example` | Find code samples |
| `<any question>` | Search all docs |

---

## Search API

```python
from search import search_docs, find_code_samples

# Search docs
results = search_docs("how to create agent")
for r in results:
    print(r['doc']['title'], r['score'])

# Find code
codes = find_code_samples("agent.json")
for c in codes:
    print(c['code'])
```
