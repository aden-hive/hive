# Why Conditional Edges Need Priority (Function Nodes)

## The problem

Function nodes return everything they computed. They don't pick one output key — they return all of them.

```python
def score_lead(inputs):
    score = compute_score(inputs["profile"])
    return {
        "score": score,
        "is_high_value": score > 80,
        "needs_enrichment": score > 50 and not inputs["profile"].get("company"),
    }
```

Lead comes in: score 92, no company on file. Output: `{"score": 92, "is_high_value": True, "needs_enrichment": True}`.

Two conditional edges leaving this node:

```
Edge A: needs_enrichment == True  → enrichment node
Edge B: is_high_value == True     → outreach node
```

Both are true. Without priority, the graph either fans out to both (wrong — you'd email someone while still enriching their data) or picks one randomly (wrong — non-deterministic).

## Priority fixes it

```
Edge A: needs_enrichment == True   priority=2  (higher = checked first)
Edge B: is_high_value == True      priority=1
Edge C: is_high_value == False     priority=0
```

Executor keeps only the highest-priority matching group. A wins. Lead gets enriched first, loops back, gets re-scored — now `needs_enrichment` is false, B wins, outreach happens.

## Why event loop nodes don't need this

The LLM understands "if/else." You tell it in the prompt: "if needs enrichment, set `needs_enrichment`. Otherwise if high value, set `approved`." It picks one. Only one conditional edge matches.

A function just returns a dict. It doesn't do "otherwise." Priority is the "otherwise" for function nodes.
