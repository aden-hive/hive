# Hello Agent (Minimal Example)

This is a minimal, end-to-end agent you can create locally. The `exports/` directory
is gitignored by default, so you create it on your machine.

## 1) Create the agent folder

```bash
mkdir -p exports/hello_agent
```

## 2) Create `agent.json`

Create `exports/hello_agent/agent.json` with:

```json
{
  "graph": {
    "id": "hello-agent-graph",
    "goal_id": "hello-goal",
    "entry_node": "hello",
    "terminal_nodes": ["hello"],
    "nodes": [
      {
        "id": "hello",
        "name": "Hello",
        "description": "Generate a friendly greeting.",
        "node_type": "llm_generate",
        "input_keys": ["name"],
        "output_keys": ["response"],
        "system_prompt": "Return JSON with key response. Greet {name} in one sentence."
      }
    ],
    "edges": []
  },
  "goal": {
    "id": "hello-goal",
    "name": "Hello Agent",
    "description": "Greet the user by name.",
    "success_criteria": [
      {
        "id": "greeted",
        "description": "The response greets the provided name.",
        "metric": "output_contains",
        "target": "name"
      }
    ]
  }
}
```

## 3) Validate and run

```bash
PYTHONPATH=core:exports python -m core validate exports/hello_agent
PYTHONPATH=core:exports python -m core run exports/hello_agent --input "{\"name\":\"Aden\"}"
```

## 4) Run without paid APIs (local model)

If you have Ollama running locally:

```bash
PYTHONPATH=core:exports python -m core --model ollama/llama3 run exports/hello_agent --input "{\"name\":\"Aden\"}"
```
